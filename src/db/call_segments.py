"""DAOs — Call Segments."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class CallSegment:
    id: Optional[int]
    call_session_id: int
    sort_order: int
    text: str
    category_id: Optional[int] = None
    deleted_at: Optional[str] = None


def save_call_segment(seg: CallSegment) -> int:
    """Insert a CallSegment row and return its new id."""
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO call_segments (call_session_id, sort_order, text, category_id)
               VALUES (?,?,?,?)""",
            (seg.call_session_id, seg.sort_order, seg.text, seg.category_id)
        )
        return cur.lastrowid


def get_call_segments(call_session_id: int) -> list[CallSegment]:
    """Return all CallSegment rows for the given call session, ordered by sort_order."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_segments WHERE call_session_id=? AND deleted_at IS NULL ORDER BY sort_order",
            (call_session_id,)
        ).fetchall()
    return [CallSegment(**dict(r)) for r in rows]


def get_call_segments_by_category_global(category_id: int) -> list[CallSegment]:
    """All CallSegment rows in this category across every call session (not
    scoped to one session) — used by Historial's global reclassify tool."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_segments WHERE category_id=? AND deleted_at IS NULL", (category_id,)
        ).fetchall()
    return [CallSegment(**dict(r)) for r in rows]


def update_call_segment_category(segment_id: int, category_id: int) -> None:
    """Reassign a single call segment's category (used by post-hoc reclassification)."""
    with database._conn() as conn:
        conn.execute(
            "UPDATE call_segments SET category_id=? WHERE id=?",
            (category_id, segment_id)
        )


def get_call_segments_by_ids(ids: list[int]) -> list[CallSegment]:
    """Return CallSegment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with database._conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM call_segments WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: CallSegment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete_call_segment(segment_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE call_segments SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), segment_id),
        )
        database._write_audit_log(conn, actor, "delete_call_segment", "call_segments", segment_id)
