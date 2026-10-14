"""
Semantic search indexing for call segments — a second Chroma-backed search
surface alongside the live in-call RAGStore. Coexists with (never
replaces) the existing full-text SQL search
(src/db/call_segments.py:search_call_segments) — this is optional,
OpenAI-gated, and degrades silently without it, same as the rest of this
codebase's RAG features.
"""

import asyncio
import logging
import os

from openai import AsyncOpenAI

from src.db.database import get_call_segments_by_ids
from src.rag.segments_store import SegmentsSearchStore

logger = logging.getLogger("call_copilot.processing.search_indexer")


def _build_openai_client() -> AsyncOpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    return AsyncOpenAI(api_key=api_key) if api_key else None


def index_segment(source: str, segment_id: int, text: str) -> bool:
    """Best-effort, sync entrypoint — bridges to the store's async
    interface via asyncio.run(). Safe because callers
    (src/processing/session_processor.py) always run inside a
    run_in_executor worker thread with no event loop of its own already
    running."""
    openai_client = _build_openai_client()
    store = SegmentsSearchStore(openai_client=openai_client)
    return asyncio.run(store.add_segment(source, segment_id, text))


async def _forget_segment_embeddings(source: str, segment_ids: list[int]) -> None:
    openai_client = _build_openai_client()
    store = SegmentsSearchStore(openai_client=openai_client)
    for segment_id in segment_ids:
        await store.delete_segment(source, segment_id)


def forget_segment_embeddings(source: str, segment_ids: list[int]) -> None:
    """Best-effort delete of segment embeddings — failures never block the
    SQLite soft-delete that already happened in the caller."""
    if not segment_ids:
        return
    try:
        asyncio.run(_forget_segment_embeddings(source, segment_ids))
    except Exception as e:
        logger.error("forget_segment_embeddings failed for source=%s ids=%s: %s", source, segment_ids, e)


async def search_segments_semantic(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search across call segments, joined back to full SQL
    rows. A composite id the store returns but that no longer resolves to
    a real row (deleted session, etc.) is silently dropped."""
    openai_client = _build_openai_client()
    store = SegmentsSearchStore(openai_client=openai_client)
    ranked = await store.search(query, top_k=top_k)

    call_ids = [seg_id for source, seg_id, _ in ranked if source == "call"]
    call_by_id = {s.id: s for s in get_call_segments_by_ids(call_ids)}

    results: list[dict] = []
    for source, seg_id, _distance in ranked:
        if source == "call" and seg_id in call_by_id:
            seg = call_by_id[seg_id]
            results.append({
                "source": "call", "id": seg.id, "text": seg.text,
                "call_session_id": seg.call_session_id,
            })
    return results
