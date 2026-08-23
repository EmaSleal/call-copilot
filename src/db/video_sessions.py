"""DAOs — Video Sessions."""

import sqlite3
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


def try_start_processing_session(title: str, url: str) -> Optional[VideoSession]:
    """Atomically check-and-claim the single processing slot for point 5
    (docs/next-steps/feature-proposals.md — MCP-triggered video
    processing): if no session is currently `status="processing"`,
    creates one directly in that status and returns it; otherwise returns
    None without creating anything.

    Uses `BEGIN IMMEDIATE` — a plain read-then-insert across two
    statements (even inside `database._conn()`'s default deferred
    transaction) has a real time-of-check-to-time-of-use race: two
    separate OS processes can both see "nothing processing" before either
    writes. This isn't hypothetical — Claude Desktop was confirmed to run
    2+ instances of the same MCP server concurrently as separate
    processes. `BEGIN IMMEDIATE` grabs sqlite's write lock before the
    SELECT, so a second concurrent caller blocks until the first commits
    and then correctly sees its row."""
    conn = sqlite3.connect(database.DB_PATH, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT 1 FROM video_sessions WHERE status='processing' AND deleted_at IS NULL LIMIT 1"
        ).fetchone()
        if row is not None:
            conn.execute("ROLLBACK")
            return None

        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO video_sessions (title, url, status, created_at) VALUES (?,?,?,?)",
            (title, url, "processing", now),
        )
        session_id = cur.lastrowid
        conn.execute("COMMIT")
        return VideoSession(id=session_id, title=title, url=url, status="processing", created_at=now)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


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
