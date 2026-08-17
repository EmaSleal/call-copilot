"""DAOs — Call Sessions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class CallSession:
    id: Optional[int]
    context: str
    transcript_path: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chroma_collection: Optional[str] = None
    profile_id: Optional[str] = None
    title: str = ""
    deleted_at: Optional[str] = None


def create_call_session(
    context: str,
    transcript_path: str,
    chroma_collection: str = "",
    profile_id: Optional[str] = None,
    title: str = "",
) -> CallSession:
    cs = CallSession(
        id=None,
        context=context,
        transcript_path=transcript_path,
        chroma_collection=chroma_collection,
        profile_id=profile_id,
        title=title,
    )
    with database._conn() as conn:
        cur = conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, chroma_collection, profile_id, created_at, title) VALUES (?,?,?,?,?,?)",
            (cs.context, cs.transcript_path, cs.chroma_collection, cs.profile_id, cs.created_at, cs.title)
        )
        cs.id = cur.lastrowid
    return cs


def get_call_sessions() -> list[CallSession]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_sessions WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [CallSession(**dict(r)) for r in rows]


def delete_call_session(call_session_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE call_segments SET deleted_at=? WHERE call_session_id=?",
            (now, call_session_id),
        )
        conn.execute("UPDATE call_sessions SET deleted_at=? WHERE id=?", (now, call_session_id))
        database._write_audit_log(conn, actor, "delete_call_session", "call_sessions", call_session_id)


def set_call_session_title(call_session_id: int, title: str) -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE call_sessions SET title=? WHERE id=?",
            (title, call_session_id)
        )
