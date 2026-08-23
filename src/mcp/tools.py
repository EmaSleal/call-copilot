"""Async MCP tool handlers for the read-only MCP server (sdd/mcp-server-read-only,
Phase 2).

Each handler wraps a sync call (an existing DAO under `src/db/database.py`,
or `src/mcp/queries.py::search_content`) via `asyncio.to_thread(...)` so the
blocking sqlite3 calls never block the async MCP event loop that
`src/mcp/server.py` runs. Every dataclass result is converted to a plain
dict via `dataclasses.asdict()` (same convention as `src/profiles/store.py`)
so results are JSON-serializable for the MCP protocol.

No tool here inserts, updates, or deletes any row (spec: Read-only
guarantee) — every handler is satisfied by an existing read-only DAO
function or `src.mcp.queries.search_content`.
"""

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from src.db import database
from src.mcp import queries as mcp_queries
from src.processing.search_indexer import search_segments_semantic


async def search_content(
    category_id: Optional[int] = None,
    technology: Optional[str] = None,
    title_query: Optional[str] = None,
    text_query: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = mcp_queries.DEFAULT_LIMIT,
    offset: int = 0,
) -> list[dict]:
    """Combinable content search over video/call segments. See
    `src.mcp.queries.search_content` for the full filter contract; this is a
    thin async wrapper — `search_content()` already returns plain dicts, so
    no further conversion is needed here."""
    return await asyncio.to_thread(
        mcp_queries.search_content,
        category_id=category_id,
        technology=technology,
        title_query=title_query,
        text_query=text_query,
        source=source,
        limit=limit,
        offset=offset,
    )


async def list_categories() -> list[dict]:
    """The full category taxonomy (top-level and subcategories), so a
    client can pick a `category_id` for `search_content` and knows which
    ids are subcategories (non-null `parent_id`) before calling it."""
    categories = await asyncio.to_thread(database.get_categories)
    return [asdict(c) for c in categories]


async def list_tools_catalog(name_query: Optional[str] = None) -> list[dict]:
    """The Tools catalog, optionally filtered client-side by a
    case-insensitive substring match on `name` — `database.get_tools()`
    takes no query parameter, so the filter is applied here rather than
    modifying `src/db/tools.py`."""
    tools_list = await asyncio.to_thread(database.get_tools)
    results = [asdict(t) for t in tools_list]
    if name_query:
        needle = name_query.strip().lower()
        results = [r for r in results if needle in r["name"].lower()]
    return results


def _report_url(html_report: Optional[str]) -> Optional[str]:
    if not html_report:
        return None
    path = Path(html_report)
    if not path.exists():
        return None
    return path.resolve().as_uri()


async def list_reports(title_query: Optional[str] = None) -> list[dict]:
    """Video sessions that already have a generated HTML report, each with
    a `file://` URL an MCP client (e.g. Claude Desktop) can open directly.
    Closes the gap where `get_session`'s `UnifiedSession` has no
    `html_report` field — call sessions have none, so it isn't part of the
    unified video/call model. Skips a session whose `html_report` row
    points at a file no longer on disk rather than returning a broken
    link. Optionally filtered client-side by a case-insensitive substring
    match on `title`, same convention as `list_tools_catalog`."""
    sessions = await asyncio.to_thread(database.get_video_sessions)
    needle = title_query.strip().lower() if title_query else None
    results = []
    for s in sessions:
        url = _report_url(s.html_report)
        if url is None:
            continue
        if needle and needle not in s.title.lower():
            continue
        results.append(
            {"id": s.id, "title": s.title, "created_at": s.created_at, "report_url": url}
        )
    return results


async def get_report_url(session_id: int) -> Optional[str]:
    """The `file://` URL for one video session's report, or `None` if the
    session doesn't exist, has no report yet, or the file was deleted
    from disk. The single-id counterpart to `list_reports` for a client
    that already has a `session_id` (e.g. from `get_session`)."""
    def _sync() -> Optional[str]:
        sessions = database.get_video_sessions()
        session = next((s for s in sessions if s.id == session_id), None)
        return _report_url(session.html_report) if session else None

    return await asyncio.to_thread(_sync)


def _get_session_sync(session_id: int, source: str) -> dict:
    sessions = database.get_unified_sessions()
    session = next(
        (s for s in sessions if s.id == session_id and s.source == source), None
    )
    segments = database.get_unified_segments(source=source, session_id=session_id)
    return {
        "session": asdict(session) if session is not None else None,
        "segments": [asdict(seg) for seg in segments],
    }


async def get_session(session_id: int, source: str) -> dict:
    """A unified session (video or call) plus its segments, combined in one
    round trip — `database.get_unified_sessions()` filtered to the matching
    id+source, plus `database.get_unified_segments(source=, session_id=)`.
    Returns `{"session": None, "segments": []}` for an unknown id+source
    pair rather than raising."""
    return await asyncio.to_thread(_get_session_sync, session_id, source)


async def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search across video AND call segments (spec: Graceful RAG
    degradation). Thin wrapper around
    `src.processing.search_indexer.search_segments_semantic` — same
    instantiation the TUI's search tab (`src/tui/tabs/search.py`) already
    uses — which itself wraps `SegmentsSearchStore.search()`
    (`src/rag/segments_store.py`) unchanged. Returns `[]` rather than
    raising when `chromadb` or `OPENAI_API_KEY` are unavailable: that no-op
    behavior already lives in `ChromaEmbeddingStore.__init__`/`.search()`
    (`src/rag/base.py`), so no extra try/except is added here — one would
    only risk masking a real bug."""
    return await search_segments_semantic(query, top_k=top_k)
