"""DAOs — Note Segments."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class NoteSegment:
    id: Optional[int]
    note_id: int
    sort_order: int
    text: str
    category_id: Optional[int] = None
    deleted_at: Optional[str] = None


def save_note_segment(seg: NoteSegment) -> int:
    """Insert a NoteSegment row and return its new id."""
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO note_segments (note_id, sort_order, text, category_id)
               VALUES (?,?,?,?)""",
            (seg.note_id, seg.sort_order, seg.text, seg.category_id)
        )
        return cur.lastrowid


def get_note_segments(note_id: int) -> list[NoteSegment]:
    """Return all NoteSegment rows for the given note, ordered by sort_order."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM note_segments WHERE note_id=? AND deleted_at IS NULL ORDER BY sort_order",
            (note_id,)
        ).fetchall()
    return [NoteSegment(**dict(r)) for r in rows]


def get_note_segments_by_category_global(category_id: int) -> list[NoteSegment]:
    """All NoteSegment rows in this category across every note (not scoped
    to one note) — used by Historial's global reclassify tool."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM note_segments WHERE category_id=? AND deleted_at IS NULL", (category_id,)
        ).fetchall()
    return [NoteSegment(**dict(r)) for r in rows]


def update_note_segment_category(segment_id: int, category_id: int) -> None:
    """Reassign a single note segment's category (used by post-hoc reclassification)."""
    with database._conn() as conn:
        conn.execute(
            "UPDATE note_segments SET category_id=? WHERE id=?",
            (category_id, segment_id)
        )


def get_note_segments_by_ids(ids: list[int]) -> list[NoteSegment]:
    """Return NoteSegment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with database._conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM note_segments WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: NoteSegment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete_note_segment(segment_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE note_segments SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), segment_id),
        )
        database._write_audit_log(conn, actor, "delete_note_segment", "note_segments", segment_id)


def next_sort_order(note_id: int) -> int:
    """MAX(sort_order)+1 for this note, 0 when empty — makes save_note's
    append path continue the existing ordering instead of restarting at 0."""
    with database._conn() as conn:
        row = conn.execute(
            "SELECT MAX(sort_order) FROM note_segments WHERE note_id=? AND deleted_at IS NULL",
            (note_id,)
        ).fetchone()
    return (row[0] + 1) if row[0] is not None else 0
