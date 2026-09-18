"""DAOs — Notes (sessions)."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class NoteSession:
    id: Optional[int]
    title: str
    normalized_title: str
    source_url: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deleted_at: Optional[str] = None


def normalize_note_title(title: str) -> str:
    """Lowercase, strip, collapse internal whitespace, strip trailing
    punctuation — the dedup key for save_note's append-by-title rule.
    Deliberately a local copy of src/db/tools.py::normalize_tool_name
    rather than an import: note dedup and tool-catalog dedup must be free
    to diverge without one silently changing the other."""
    s = title.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]+$", "", s)
    return s.strip()


def create_note_session(title: str, source_url: str = "") -> NoteSession:
    ns = NoteSession(
        id=None,
        title=title,
        normalized_title=normalize_note_title(title),
        source_url=source_url,
    )
    with database._conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (title, normalized_title, source_url, created_at) VALUES (?,?,?,?)",
            (ns.title, ns.normalized_title, ns.source_url, ns.created_at),
        )
        ns.id = cur.lastrowid
    return ns


def find_note_session_by_title(title: str) -> Optional[NoteSession]:
    """Newest non-deleted note whose normalized_title matches. None on miss."""
    normalized = normalize_note_title(title)
    with database._conn() as conn:
        row = conn.execute(
            "SELECT * FROM notes WHERE normalized_title=? AND deleted_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (normalized,),
        ).fetchone()
    return NoteSession(**dict(row)) if row else None


def get_note_sessions() -> list[NoteSession]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [NoteSession(**dict(r)) for r in rows]


def delete_note_session(note_id: int, actor: str = "human") -> None:
    """Soft-delete the note AND its segments, + audit log — mirrors
    call_sessions.delete_call_session exactly."""
    with database._conn() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE note_segments SET deleted_at=? WHERE note_id=?",
            (now, note_id),
        )
        conn.execute("UPDATE notes SET deleted_at=? WHERE id=?", (now, note_id))
        database._write_audit_log(conn, actor, "delete_note_session", "notes", note_id)
