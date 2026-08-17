"""DAOs — Unified Segments (read-only view over segments + call_segments)."""

from dataclasses import dataclass
from typing import Optional

from src.db import database


@dataclass
class UnifiedSegment:
    """Read-only row from the `unified_segments` view (video + call, same categories)."""
    id: int
    source: str          # "video" | "call"
    session_id: int
    text: str
    category_id: Optional[int]
    position: float


@dataclass
class UnifiedSession:
    """Read-only row from the `unified_sessions` view (video + call)."""
    id: int
    source: str          # "video" | "call"
    title: str
    created_at: str


def get_unified_segments(
    source: Optional[str] = None, session_id: Optional[int] = None
) -> list[UnifiedSegment]:
    """
    Return rows from the unified_segments view, optionally filtered by source
    ('video'|'call') and/or session_id. Since video_sessions.id and
    call_sessions.id are independent sequences, filtering by session_id alone
    without source could mix rows from different sources that share the same id.
    """
    clauses = []
    params: list = []
    if source:
        clauses.append("source=?")
        params.append(source)
    if session_id is not None:
        clauses.append("session_id=?")
        params.append(session_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with database._conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM unified_segments {where} ORDER BY session_id, position",
            params
        ).fetchall()
    return [UnifiedSegment(**dict(r)) for r in rows]


def get_unified_sessions() -> list[UnifiedSession]:
    """Return rows from the unified_sessions view, newest first."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM unified_sessions ORDER BY created_at DESC"
        ).fetchall()
    return [UnifiedSession(**dict(r)) for r in rows]
