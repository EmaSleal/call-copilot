"""DAOs — Unified Segments (read-only view over call_segments, keyed by
source so a second source can be added later without an API change)."""

from dataclasses import dataclass
from typing import Optional

from src.db import database


@dataclass
class UnifiedSegment:
    """Read-only row from the `unified_segments` view. Only source today is "call"."""
    id: int
    source: str          # "call"
    session_id: int
    text: str
    category_id: Optional[int]
    position: float


@dataclass
class UnifiedSession:
    """Read-only row from the `unified_sessions` view. Only source today is "call"."""
    id: int
    source: str          # "call"
    title: str
    created_at: str


def get_unified_segments(
    source: Optional[str] = None, session_id: Optional[int] = None
) -> list[UnifiedSegment]:
    """
    Return rows from the unified_segments view, optionally filtered by
    source ('call') and/or session_id.
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
