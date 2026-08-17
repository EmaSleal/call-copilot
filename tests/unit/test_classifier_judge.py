"""
Unit tests for PR2 — src/video/classifier.py dedup additions.

Two concerns, per design (sdd/categorias-jerarquicas, design obs #823, decision A5):

1. CHARACTERIZATION tests of the CURRENT per-backend request kwargs for
   `_call_llm` (used by classify_segments_batch) and `_call_suggest_llm`
   (used by suggest_new_categories) — request shape is produced by the
   shared `call_llm_backend()` helper in src/llm/backend.py (also used by
   tool_extractor.py and session_processor.py, which previously
   hand-rolled the same claude/ollama/gpt triple-branch independently).
   These are the regression safety net for the one part of this PR with
   real regression exposure (the live classification path had no
   per-backend test coverage before this change).

2. RED tests for the new `judge_category_duplicate()` parse/validation
   matrix, which does not exist yet at RED time.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import Category


# ─────────────────────────────────────────────────────────────
# Characterization — _call_llm (classify_segments_batch's backend call)
# ─────────────────────────────────────────────────────────────

class TestCallLlmCharacterization:
    def test_ollama_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"classifications": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = classifier._call_llm("some prompt", "ollama")

        assert result == '{"classifications": []}'
        _, client_kwargs = mock_openai_cls.call_args
        assert client_kwargs["api_key"] == "ollama"
        assert "base_url" in client_kwargs

        _, create_kwargs = mock_client.chat.completions.create.call_args
        assert create_kwargs["max_completion_tokens"] == 512
        assert create_kwargs["temperature"] == 0.0
        assert create_kwargs["extra_body"] == {"options": {"think": False, "num_ctx": 4096}}
        assert create_kwargs["messages"][1]["content"].startswith("/no_think\n")
        assert "response_format" not in create_kwargs

    def test_gpt_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"classifications": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = classifier._call_llm("some prompt", "gpt")

        assert result == '{"classifications": []}'
        _, client_kwargs = mock_openai_cls.call_args
        assert client_kwargs["api_key"] != "ollama"

        _, create_kwargs = mock_client.chat.completions.create.call_args
        assert create_kwargs["model"] == "gpt-5.4-nano"
        assert create_kwargs["max_completion_tokens"] == 512
        assert create_kwargs["temperature"] == 0.0
        assert create_kwargs["response_format"] == {"type": "json_object"}

    def test_claude_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_anthropic_cls = MagicMock()
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"classifications": []}')]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        with patch.object(llm_backend.anthropic, "Anthropic", mock_anthropic_cls):
            result = classifier._call_llm("some prompt", "claude")

        assert result == '{"classifications": []}'
        _, create_kwargs = mock_client.messages.create.call_args
        assert create_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert create_kwargs["max_tokens"] == 512
        assert create_kwargs["system"] == classifier._SYSTEM


# ─────────────────────────────────────────────────────────────
# Characterization — _call_suggest_llm (suggest_new_categories's backend call)
# ─────────────────────────────────────────────────────────────

class TestCallSuggestLlmCharacterization:
    def test_ollama_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"suggestions": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = classifier._call_suggest_llm("some prompt", "ollama")

        assert result == '{"suggestions": []}'
        _, create_kwargs = mock_client.chat.completions.create.call_args
        assert create_kwargs["max_completion_tokens"] == 512
        assert create_kwargs["temperature"] == 0.3
        assert create_kwargs["extra_body"] == {"options": {"think": False, "num_ctx": 8192}}
        assert "response_format" not in create_kwargs

    def test_gpt_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"suggestions": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = classifier._call_suggest_llm("some prompt", "gpt")

        assert result == '{"suggestions": []}'
        _, create_kwargs = mock_client.chat.completions.create.call_args
        assert create_kwargs["temperature"] == 0.3
        assert create_kwargs["response_format"] == {"type": "json_object"}

    def test_claude_backend_kwargs(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.video import classifier

        mock_anthropic_cls = MagicMock()
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"suggestions": []}')]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        with patch.object(llm_backend.anthropic, "Anthropic", mock_anthropic_cls):
            result = classifier._call_suggest_llm("some prompt", "claude")

        assert result == '{"suggestions": []}'
        _, create_kwargs = mock_client.messages.create.call_args
        assert create_kwargs["max_tokens"] == 512
        assert create_kwargs["system"] == classifier._SUGGEST_SYSTEM


# ─────────────────────────────────────────────────────────────
# judge_category_duplicate() — parse/validation matrix (RED — does not exist yet)
# ─────────────────────────────────────────────────────────────

EXISTING = [
    Category(id=1, name="Diseño UI/UX", description="Tipografía, color y jerarquía visual."),
    Category(id=2, name="Marketing", description="Estrategias de difusión y crecimiento."),
]


class TestJudgeCategoryDuplicate:
    def test_valid_match_returns_category_id(self):
        from src.video import classifier

        raw = json.dumps({"verdict": "MATCH", "category_id": 1})
        with patch.object(classifier, "_call_judge_llm", return_value=raw):
            result = classifier.judge_category_duplicate("Tipografía", "Reglas tipográficas", EXISTING)

        assert result == 1

    def test_match_with_unknown_id_returns_none(self):
        from src.video import classifier

        raw = json.dumps({"verdict": "MATCH", "category_id": 999})
        with patch.object(classifier, "_call_judge_llm", return_value=raw):
            result = classifier.judge_category_duplicate("Algo nuevo", "desc", EXISTING)

        assert result is None

    def test_new_verdict_returns_none(self):
        from src.video import classifier

        raw = json.dumps({"verdict": "NEW", "category_id": None})
        with patch.object(classifier, "_call_judge_llm", return_value=raw):
            result = classifier.judge_category_duplicate("Cocina", "Recetas y técnicas culinarias", EXISTING)

        assert result is None

    def test_junk_text_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_judge_llm", return_value="not json at all {{{"):
            result = classifier.judge_category_duplicate("Cocina", "desc", EXISTING)

        assert result is None

    def test_empty_response_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_judge_llm", return_value=""):
            result = classifier.judge_category_duplicate("Cocina", "desc", EXISTING)

        assert result is None

    def test_backend_exception_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_judge_llm", side_effect=RuntimeError("unreachable")):
            result = classifier.judge_category_duplicate("Cocina", "desc", EXISTING)

        assert result is None

    def test_no_existing_categories_returns_none_without_calling_backend(self):
        from src.video import classifier

        with patch.object(classifier, "_call_judge_llm") as mock_call:
            result = classifier.judge_category_duplicate("Cocina", "desc", [])

        assert result is None
        mock_call.assert_not_called()
