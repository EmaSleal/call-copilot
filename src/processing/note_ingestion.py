"""Note ingestion — call-copilot's fourth write surface.

Pure storage + semantic indexing, the same contract as
`src.processing.tool_extractor.save_researched_tool`: this NEVER calls an
LLM and never chunks anything. The calling agent (e.g. Claude Desktop) has
already split the knowledge into per-subtopic `segments`; this module only
persists them and embeds each one into `SegmentsSearchStore` under
`source="note"`.
"""

import asyncio
import os

from openai import AsyncOpenAI

from src.db.database import (
    NoteSegment,
    NoteSession,
    create_note_session,
    find_note_session_by_title,
    next_sort_order,
    save_note_segment,
)
from src.rag.segments_store import SegmentsSearchStore


def _build_openai_client() -> AsyncOpenAI | None:
    """Build an AsyncOpenAI client, or None when OPENAI_API_KEY is not configured."""
    api_key = os.getenv("OPENAI_API_KEY")
    return AsyncOpenAI(api_key=api_key) if api_key else None


def save_note(
    title: str,
    segments: list[str],
    *,
    source_url: str = "",
) -> tuple[NoteSession, int, bool]:
    """Persist a note and its segments, appending to an existing note when
    the normalized title already exists.

    Returns (note, segments_added, created) — created=False on an append.

    Raises ValueError for an empty/whitespace-only title or a `segments`
    list that is empty or contains only blank strings (never produces a
    title-only note), mirroring save_researched_tool's empty-name guard.
    """
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    texts = [s.strip() for s in (segments or []) if s and s.strip()]
    if not texts:
        raise ValueError("segments is required")

    existing = find_note_session_by_title(title)
    created = existing is None
    note = existing or create_note_session(title, source_url=source_url)

    start = next_sort_order(note.id)
    indexed: list[tuple[int, str]] = []
    for offset, text in enumerate(texts):
        seg_id = save_note_segment(
            NoteSegment(id=None, note_id=note.id, sort_order=start + offset, text=text)
        )
        indexed.append((seg_id, text))

    asyncio.run(_embed_note_segments(indexed))
    return note, len(indexed), created


async def _embed_note_segments(pairs: list[tuple[int, str]]) -> None:
    """Best-effort — SegmentsSearchStore.add_segment no-ops (returns False,
    never raises) without chromadb or OPENAI_API_KEY. Mirrors
    tool_extractor._embed_tools: one store, one event loop for the whole
    batch, instead of search_indexer.index_segment's one-loop-per-segment."""
    store = SegmentsSearchStore(openai_client=_build_openai_client())
    for segment_id, text in pairs:
        await store.add_segment("note", segment_id, text)
