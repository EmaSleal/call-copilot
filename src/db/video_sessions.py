"""DAOs — Video Sessions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class VideoSession:
    id: Optional[int]
    title: str
    url: str
    status: str          # pending | processing | done | error
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    html_report: Optional[str] = None
    error_msg: Optional[str] = None
    deleted_at: Optional[str] = None


def create_video_session(title: str, url: str) -> VideoSession:
    s = VideoSession(id=None, title=title, url=url, status="pending")
    with database._conn() as conn:
        cur = conn.execute(
            "INSERT INTO video_sessions (title, url, status, created_at) VALUES (?,?,?,?)",
            (s.title, s.url, s.status, s.created_at)
        )
        s.id = cur.lastrowid
    return s


def delete_video_session(session_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        now = datetime.now().isoformat()
        conn.execute("UPDATE segments SET deleted_at=? WHERE session_id=?", (now, session_id))
        conn.execute("UPDATE video_sessions SET deleted_at=? WHERE id=?", (now, session_id))
        database._write_audit_log(conn, actor, "delete_video_session", "video_sessions", session_id)


def update_session_status(session_id: int, status: str,
                           html_report: str = None, error_msg: str = None) -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE video_sessions SET status=?, html_report=?, error_msg=? WHERE id=?",
            (status, html_report, error_msg, session_id)
        )


def get_video_sessions(status_filter: str = None) -> list[VideoSession]:
    with database._conn() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM video_sessions WHERE status=? AND deleted_at IS NULL ORDER BY created_at DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM video_sessions WHERE deleted_at IS NULL ORDER BY created_at DESC"
            ).fetchall()
    return [VideoSession(**dict(r)) for r in rows]
