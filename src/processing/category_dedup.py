"""
Shared semantic dedup entry point for AI-suggested categories — one
sync bridge used by both TUI call sites (src/tui/tabs/video.py and
src/tui/screens/category_reclassify_modal.py, wired in PR3) so neither
duplicates the verdict logic (spec: Shared dedup helper).

Hybrid backend selection (spec: Hybrid backend selection):
  - OPENAI_API_KEY set   -> embeddings-based similarity check (CategoriesStore)
  - OPENAI_API_KEY unset -> LLM-as-judge check on the active LLM_BACKEND
    (src.video.classifier.judge_category_duplicate)

Fail-open by design (spec: Fail-open on any uncertainty; D7): the entire
per-suggestion body runs inside one try/except Exception. dedup_suggestions
NEVER raises and NEVER returns a partial/inconsistent list — every failure
mode resolves to match=None, backend="none" (i.e. "genuinely new").
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from src.db.database import Category
from src.rag.categories_store import CategoriesStore, embedding_text
from src.video.classifier import judge_category_duplicate

logger = logging.getLogger("call_copilot.processing.category_dedup")

MAX_DISTANCE = float(os.getenv("CATEGORY_DEDUP_MAX_DISTANCE", "0.15"))
TOP_K = 3


@dataclass
class DedupVerdict:
    suggestion: dict
    match: Optional[Category]
    distance: Optional[float]
    backend: str  # "exact" | "embeddings" | "llm-judge" | "none"


def _build_openai_client():
    """Local import + lazy construction mirrors tool_extractor/search_indexer's
    _build_openai_client() precedent: None without OPENAI_API_KEY, never raises."""
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    return AsyncOpenAI(api_key=api_key) if api_key else None


def _exact_match(name: str, existing: list[Category]) -> Optional[Category]:
    normalized = name.strip().lower()
    for c in existing:
        if c.name.strip().lower() == normalized:
            return c
    return None


async def _embeddings_match(
    name: str, description: str, existing: list[Category]
) -> tuple[Optional[Category], Optional[float]]:
    openai_client = _build_openai_client()
    store = CategoriesStore(openai_client=openai_client)
    by_id = {c.id: c for c in existing}
    ranked = await store.search(embedding_text(name, description), top_k=TOP_K)
    for category_id, distance in ranked:
        if distance <= MAX_DISTANCE and category_id in by_id:
            return by_id[category_id], distance
    return None, None


def _judge_match(
    name: str, description: str, existing: list[Category]
) -> Optional[Category]:
    match_id = judge_category_duplicate(name, description, existing)
    if match_id is None:
        return None
    return next((c for c in existing if c.id == match_id), None)


def _dedup_one(suggestion: dict, existing: list[Category]) -> DedupVerdict:
    name = suggestion.get("name", "")
    description = suggestion.get("description", "")

    exact = _exact_match(name, existing)
    if exact is not None:
        return DedupVerdict(suggestion=suggestion, match=exact, distance=0.0, backend="exact")

    if os.getenv("OPENAI_API_KEY"):
        import asyncio

        match, distance = asyncio.run(_embeddings_match(name, description, existing))
        if match is not None:
            return DedupVerdict(suggestion=suggestion, match=match, distance=distance, backend="embeddings")
        return DedupVerdict(suggestion=suggestion, match=None, distance=None, backend="none")

    match = _judge_match(name, description, existing)
    if match is not None:
        return DedupVerdict(suggestion=suggestion, match=match, distance=None, backend="llm-judge")
    return DedupVerdict(suggestion=suggestion, match=None, distance=None, backend="none")


def dedup_suggestions(suggestions: list[dict], existing: list[Category]) -> list[DedupVerdict]:
    """Evaluate every suggestion against `existing` categories. NEVER raises —
    any failure (missing backend, timeout, unparseable output, embeddings
    service error, missing chromadb, missing OpenAI key) resolves that single
    suggestion to match=None, backend="none" without affecting the rest of
    the list."""
    results: list[DedupVerdict] = []
    for suggestion in suggestions:
        try:
            results.append(_dedup_one(suggestion, existing))
        except Exception as e:
            logger.error("dedup_suggestions failed for %r: %s", suggestion.get("name"), e)
            results.append(DedupVerdict(suggestion=suggestion, match=None, distance=None, backend="none"))
    return results


async def _sync_category_embedding(category: Category) -> None:
    openai_client = _build_openai_client()
    store = CategoriesStore(openai_client=openai_client)
    await store.upsert_category(category.id, embedding_text(category.name, category.description))


def sync_category_embedding(category: Category) -> None:
    """Best-effort upsert of a category's embedding — its own failures never
    block the SQLite write that already happened in the caller."""
    import asyncio

    try:
        asyncio.run(_sync_category_embedding(category))
    except Exception as e:
        logger.error("sync_category_embedding failed for category_id=%s: %s", category.id, e)


async def _forget_category_embedding(category_id: int) -> None:
    openai_client = _build_openai_client()
    store = CategoriesStore(openai_client=openai_client)
    await store.delete_category(category_id)


def forget_category_embedding(category_id: int) -> None:
    """Best-effort delete of a category's embedding — its own failures never
    block the SQLite delete that already happened in the caller."""
    import asyncio

    try:
        asyncio.run(_forget_category_embedding(category_id))
    except Exception as e:
        logger.error("forget_category_embedding failed for category_id=%s: %s", category_id, e)
