"""DAOs — Tool Mentions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class ToolMention:
    id: Optional[int]
    tool_id: int
    call_session_id: int
    context_snippet: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deleted_at: Optional[str] = None


def save_tool_mention(m: ToolMention) -> int:
    """Insert a ToolMention row and return its new id. No cap — unlimited retention."""
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO tool_mentions (tool_id, call_session_id, context_snippet, created_at)
               VALUES (?,?,?,?)""",
            (m.tool_id, m.call_session_id, m.context_snippet, m.created_at)
        )
        return cur.lastrowid


def get_tool_mentions(tool_id: int) -> list[ToolMention]:
    """Return all ToolMention rows for a tool, ordered oldest-first. Unbounded."""
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_mentions WHERE tool_id=? AND deleted_at IS NULL ORDER BY id",
            (tool_id,)
        ).fetchall()
    return [ToolMention(**dict(r)) for r in rows]


def delete_tool_mention(mention_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE tool_mentions SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), mention_id),
        )
        database._write_audit_log(conn, actor, "delete_tool_mention", "tool_mentions", mention_id)
