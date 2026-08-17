"""DAOs — Segments."""

from dataclasses import dataclass
from typing import Optional

from src.db import database


@dataclass
class Segment:
    id: Optional[int]
    session_id: int
    start_s: float
    end_s: float
    text: str
    category_id: Optional[int] = None
    keyframe_path: Optional[str] = None
    deleted_at: Optional[str] = None


def save_segment(seg: Segment) -> Segment:
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO segments
               (session_id, start_s, end_s, text, category_id, keyframe_path)
               VALUES (?,?,?,?,?,?)""",
            (seg.session_id, seg.start_s, seg.end_s,
             seg.text, seg.category_id, seg.keyframe_path)
        )
        seg.id = cur.lastrowid
    return seg


def get_segments(session_id: int) -> list[Segment]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id=? AND deleted_at IS NULL ORDER BY start_s",
            (session_id,)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def update_segment_category(segment_id: int, category_id: int) -> None:
    """Reassign a single segment's category (used by post-hoc reclassification)."""
    with database._conn() as conn:
        conn.execute(
            "UPDATE segments SET category_id=? WHERE id=?",
            (category_id, segment_id)
        )


def get_segments_by_category(session_id: int, category_id: Optional[int]) -> list[Segment]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id=? AND category_id IS ? AND deleted_at IS NULL ORDER BY start_s",
            (session_id, category_id)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def get_segments_by_category_global(category_id: int) -> list[Segment]:
    """All Segment rows in this category across every video session (not
    scoped to one session) — used by Historial's global reclassify tool."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE category_id=? AND deleted_at IS NULL", (category_id,)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def get_segments_by_ids(ids: list[int]) -> list[Segment]:
    """Return Segment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with database._conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM segments WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: Segment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def search_segments(query: str, category_id: int = None) -> list[dict]:
    """Búsqueda de texto en segmentos, con join a sesión y categoría."""
    with database._conn() as conn:
        sql = """
            SELECT s.*, c.name as cat_name, c.color as cat_color,
                   vs.title as session_title, vs.url as session_url
            FROM segments s
            LEFT JOIN categories c ON s.category_id = c.id
            LEFT JOIN video_sessions vs ON s.session_id = vs.id
            WHERE s.text LIKE ? AND s.deleted_at IS NULL
        """
        params: list = [f"%{query}%"]
        if category_id:
            sql += " AND s.category_id = ?"
            params.append(category_id)
        sql += " ORDER BY vs.created_at DESC, s.start_s"
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
