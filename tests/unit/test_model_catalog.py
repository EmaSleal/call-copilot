"""
Unit tests for src.llm.model_catalog — live per-provider model discovery
with local JSON cache, TTL, and static fallback.

No real network calls: Anthropic/OpenAI clients are monkeypatched with fake
classes returning fixture-shaped payloads (mirrors tests/unit/test_provider_prompt.py's
fake-client convention).
"""

import json
import time

import pytest

from src.llm import model_catalog
from src.profiles.models import AVAILABLE_MODELS


# ── Fixture payload shapes (mirror the real SDK response objects) ───────────

class _FakeAnthropicModel:
    def __init__(self, id, display_name, max_input_tokens=None):
        self.id = id
        self.display_name = display_name
        self.max_input_tokens = max_input_tokens


class _FakeOpenAIModel:
    def __init__(self, id):
        self.id = id


def _fake_anthropic_client_factory(page):
    class FakeModels:
        def list(self):
            return page

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    return FakeClient


def _fake_openai_client_factory(page):
    class FakeModels:
        def list(self):
            return page

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    return FakeClient


# ── is_chat_model_id ──────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id,expected", [
    ("gpt-5.6-terra", True),
    ("gpt-4o-mini", True),
    ("o1-preview", True),
    ("o3-mini", True),
    ("chatgpt-4o-latest", True),
    ("whisper-1", False),
    ("tts-1-hd", False),
    ("dall-e-3", False),
    ("text-embedding-3-large", False),
    ("text-moderation-latest", False),
    ("davinci-002", False),
    ("babbage-002", False),
    ("claude-opus-4", False),
])
def test_is_chat_model_id_table(model_id, expected):
    assert model_catalog.is_chat_model_id(model_id) is expected


# ── provider_of_model_id ──────────────────────────────────────────────────

@pytest.mark.parametrize("model_id,expected", [
    ("gpt-5.6-terra", "gpt"),
    ("o1-preview", "gpt"),
    ("o3-mini", "gpt"),
    ("chatgpt-4o-latest", "gpt"),
    ("claude-haiku-4-5-20251001", "claude"),
    ("claude-opus-4", "claude"),
    ("", None),
    ("llama-3-70b", None),
])
def test_provider_of_model_id_table(model_id, expected):
    assert model_catalog.provider_of_model_id(model_id) == expected


# ── Normalizers (fake clients, no network) ───────────────────────────────────

class TestAnthropicNormalizer:
    def test_normalizes_fixture_payload(self, monkeypatch):
        page = [_FakeAnthropicModel("claude-haiku-4-5-20251001", "Claude Haiku 4.5", 200000)]
        monkeypatch.setattr(
            model_catalog.anthropic, "Anthropic", _fake_anthropic_client_factory(page)
        )
        result = model_catalog.list_anthropic_models("key")
        assert result == [
            model_catalog.ModelInfo(
                id="claude-haiku-4-5-20251001",
                label="Claude Haiku 4.5",
                max_input_tokens=200000,
            )
        ]

    def test_falls_back_to_id_when_no_display_name(self, monkeypatch):
        page = [_FakeAnthropicModel("claude-x", "")]
        monkeypatch.setattr(
            model_catalog.anthropic, "Anthropic", _fake_anthropic_client_factory(page)
        )
        result = model_catalog.list_anthropic_models("key")
        assert result[0].label == "claude-x"


class TestOpenAINormalizer:
    def test_filters_non_chat_ids(self, monkeypatch):
        page = [
            _FakeOpenAIModel("gpt-5.6-terra"),
            _FakeOpenAIModel("whisper-1"),
            _FakeOpenAIModel("text-embedding-3-large"),
            _FakeOpenAIModel("o1-preview"),
        ]
        monkeypatch.setattr(
            model_catalog.openai, "OpenAI", _fake_openai_client_factory(page)
        )
        result = model_catalog.list_openai_models("key")
        ids = [m.id for m in result]
        assert ids == ["gpt-5.6-terra", "o1-preview"]


# ── list_models: cache / TTL / fallback ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the module cache at a tmp_path file for every test in this file."""
    monkeypatch.setattr(model_catalog, "_CACHE_PATH", tmp_path / "model_catalog_cache.json")
    yield


class TestListModelsFallback:
    def test_missing_key_returns_static_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = model_catalog.list_models("gpt")
        expected_ids = [model_id for model_id, _ in AVAILABLE_MODELS]
        assert [m.id for m in result] == expected_ids

    def test_api_exception_returns_static_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")

        def _raise(api_key):
            raise RuntimeError("network down")

        monkeypatch.setattr(model_catalog, "list_anthropic_models", _raise)
        result = model_catalog.list_models("claude")
        expected_ids = [model_id for model_id, _ in AVAILABLE_MODELS]
        assert [m.id for m in result] == expected_ids

    def test_fallback_result_is_never_cached(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        model_catalog.list_models("gpt")
        assert not model_catalog._CACHE_PATH.exists()

    def test_unsupported_provider_returns_static_fallback(self):
        result = model_catalog.list_models("ollama")
        expected_ids = [model_id for model_id, _ in AVAILABLE_MODELS]
        assert [m.id for m in result] == expected_ids

    def test_corrupt_cache_file_is_tolerated(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        model_catalog._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        model_catalog._CACHE_PATH.write_text("{not valid json")

        page = [_FakeOpenAIModel("gpt-5.6-terra")]
        monkeypatch.setattr(
            model_catalog.openai, "OpenAI", _fake_openai_client_factory(page)
        )
        result = model_catalog.list_models("gpt")
        assert [m.id for m in result] == ["gpt-5.6-terra"]


class TestListModelsCacheAndTTL:
    def test_cache_hit_within_ttl_skips_new_fetch(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        call_count = {"n": 0}

        page = [_FakeOpenAIModel("gpt-5.6-terra")]

        def _factory(api_key):
            call_count["n"] += 1
            return _fake_openai_client_factory(page)(api_key)

        monkeypatch.setattr(model_catalog.openai, "OpenAI", _factory)

        clock = {"t": 1_000_000.0}
        monkeypatch.setattr(model_catalog.time, "time", lambda: clock["t"])

        first = model_catalog.list_models("gpt")
        assert call_count["n"] == 1
        assert [m.id for m in first] == ["gpt-5.6-terra"]

        clock["t"] += 60  # well within the 24h TTL
        second = model_catalog.list_models("gpt")
        assert call_count["n"] == 1  # no new fetch
        assert [m.id for m in second] == ["gpt-5.6-terra"]

    def test_cache_expires_after_ttl(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        call_count = {"n": 0}

        page = [_FakeOpenAIModel("gpt-5.6-terra")]

        def _factory(api_key):
            call_count["n"] += 1
            return _fake_openai_client_factory(page)(api_key)

        monkeypatch.setattr(model_catalog.openai, "OpenAI", _factory)

        clock = {"t": 1_000_000.0}
        monkeypatch.setattr(model_catalog.time, "time", lambda: clock["t"])

        model_catalog.list_models("gpt")
        assert call_count["n"] == 1

        clock["t"] += model_catalog._TTL_SECONDS + 1
        model_catalog.list_models("gpt")
        assert call_count["n"] == 2  # cache expired, re-fetched

    def test_force_refresh_bypasses_cache(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        call_count = {"n": 0}

        page = [_FakeOpenAIModel("gpt-5.6-terra")]

        def _factory(api_key):
            call_count["n"] += 1
            return _fake_openai_client_factory(page)(api_key)

        monkeypatch.setattr(model_catalog.openai, "OpenAI", _factory)

        model_catalog.list_models("gpt")
        assert call_count["n"] == 1
        model_catalog.list_models("gpt", force_refresh=True)
        assert call_count["n"] == 2


class TestInvalidate:
    def test_invalidate_specific_provider_clears_only_that_entry(self, monkeypatch):
        monkeypatch.setattr(model_catalog, "_save_cache", model_catalog._save_cache)
        model_catalog._save_cache({
            "gpt": {"fetched_at": time.time(), "models": [["gpt-5.6-terra", "GPT"]]},
            "claude": {"fetched_at": time.time(), "models": [["claude-x", "Claude"]]},
        })
        model_catalog.invalidate("gpt")
        remaining = model_catalog._load_cache()
        assert "gpt" not in remaining
        assert "claude" in remaining

    def test_invalidate_all_clears_entire_cache(self):
        model_catalog._save_cache({
            "gpt": {"fetched_at": time.time(), "models": [["gpt-5.6-terra", "GPT"]]},
        })
        model_catalog.invalidate()
        assert model_catalog._load_cache() == {}
