"""
Live per-provider LLM model discovery, with local JSON cache (TTL) and a
static fallback. Used by the profile model-selector dropdown, never on the
active-call hot path (see provider_of_model_id() for the offline check used
there instead — src/core/pipeline.py:resolve_override).

Anthropic's Models API (client.models.list()) already returns display_name +
capabilities, so it needs no client-side filtering. OpenAI's models.list()
returns ALL model ids (whisper/tts/dall-e/embeddings included) with no type
field to filter on, so is_chat_model_id() applies an allowlist-first
heuristic — intentionally not meant to be perfect on the first pass.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import openai

from src.profiles.models import AVAILABLE_MODELS

logger = logging.getLogger("call_copilot.llm.model_catalog")

_CACHE_PATH = Path("data/model_catalog_cache.json")
_CACHE_VERSION = 1
_TTL_SECONDS = 24 * 60 * 60

_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
_ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

# Allowlist-first: a chat-model id must start with one of these prefixes.
_CHAT_ID_PREFIXES = ("gpt-", "o1-", "o3-", "chatgpt-")
# Excluded even if a prefix would otherwise match (defense in depth).
_NON_CHAT_MARKERS = (
    "whisper", "tts", "dall-e", "embedding", "moderation", "davinci", "babbage",
)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    max_input_tokens: int | None = None


def is_chat_model_id(model_id: str) -> bool:
    """Client-side heuristic filter for OpenAI's unfiltered models.list()."""
    lowered = model_id.lower()
    if any(marker in lowered for marker in _NON_CHAT_MARKERS):
        return False
    return lowered.startswith(_CHAT_ID_PREFIXES)


def provider_of_model_id(model_id: str) -> str | None:
    """Pure prefix map, no network — used on the active-call hot path to
    validate a profile's model override against the active backend."""
    if not model_id:
        return None
    lowered = model_id.lower()
    if lowered.startswith("claude-"):
        return "claude"
    if lowered.startswith(_CHAT_ID_PREFIXES):
        return "gpt"
    return None


def _fallback_models() -> list[ModelInfo]:
    return [ModelInfo(id=model_id, label=label) for model_id, label in AVAILABLE_MODELS]


def list_anthropic_models(api_key: str) -> list[ModelInfo]:
    client = anthropic.Anthropic(api_key=api_key)
    page = client.models.list()
    return [
        ModelInfo(
            id=m.id,
            label=getattr(m, "display_name", "") or m.id,
            max_input_tokens=getattr(m, "max_input_tokens", None),
        )
        for m in page
    ]


def list_openai_models(api_key: str) -> list[ModelInfo]:
    client = openai.OpenAI(api_key=api_key)
    page = client.models.list()
    return [ModelInfo(id=m.id, label=m.id) for m in page if is_chat_model_id(m.id)]


def _load_cache() -> dict:
    try:
        data = json.loads(_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}
    if data.get("version") != _CACHE_VERSION:
        return {}
    return data.get("providers", {})


def _save_cache(providers: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps({"version": _CACHE_VERSION, "providers": providers}))
    except OSError as e:
        logger.warning("no se pudo escribir la cache de modelos: %s", type(e).__name__)


def invalidate(provider: str | None = None) -> None:
    """Drop the cached catalog for one provider, or the entire cache when
    provider is None. Called on manual refresh and on API-key writes."""
    if provider is None:
        _save_cache({})
        return
    providers = _load_cache()
    providers.pop(provider, None)
    _save_cache(providers)


def list_models(provider: str, *, force_refresh: bool = False) -> list[ModelInfo]:
    """Live catalog for `provider` ("gpt" | "claude"), cached with a 24h TTL.

    Falls back to the static AVAILABLE_MODELS list (never cached) when the
    provider has no discovery support, no API key is configured, or the
    live call raises for any reason (network/auth/rate-limit/5xx)."""
    fetchers = {"gpt": (_OPENAI_API_KEY_ENV, list_openai_models),
                "claude": (_ANTHROPIC_API_KEY_ENV, list_anthropic_models)}
    if provider not in fetchers:
        return _fallback_models()

    key_env, fetch = fetchers[provider]
    api_key = os.getenv(key_env, "")
    if not api_key:
        return _fallback_models()

    providers_cache = _load_cache()
    cached = providers_cache.get(provider)
    now = time.time()
    if not force_refresh and cached and (now - cached.get("fetched_at", 0)) < _TTL_SECONDS:
        return [ModelInfo(id=i, label=l) for i, l in cached.get("models", [])]

    try:
        models = fetch(api_key)
    except Exception as e:
        logger.warning("model discovery failed for %s: %s", provider, type(e).__name__)
        return _fallback_models()

    providers_cache[provider] = {
        "fetched_at": now,
        "models": [[m.id, m.label] for m in models],
    }
    _save_cache(providers_cache)
    return models
