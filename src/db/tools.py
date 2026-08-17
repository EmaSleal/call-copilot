"""DAOs — Tools Catalog."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class Tool:
    id: Optional[int]
    name: str
    normalized_name: str
    category: str = ""
    description: str = ""
    summary: str = ""
    tags: str = ""  # JSON-encoded list
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deleted_at: Optional[str] = None


def normalize_tool_name(name: str) -> str:
    """Lowercase, strip, collapse internal whitespace, strip trailing punctuation."""
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]+$", "", s)
    return s.strip()


def create_tool(t: Tool) -> Tool:
    """Insert a new Tool row and set its .id."""
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO tools (name, normalized_name, category, description, summary, tags, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (t.name, t.normalized_name, t.category, t.description, t.summary, t.tags, t.created_at)
        )
        t.id = cur.lastrowid
    return t


def find_tool_by_name(name: str) -> Optional[Tool]:
    """Look up a Tool by normalized name; returns None on miss."""
    normalized = normalize_tool_name(name)
    with database._conn() as conn:
        row = conn.execute(
            "SELECT * FROM tools WHERE normalized_name=? AND deleted_at IS NULL", (normalized,)
        ).fetchone()
    return Tool(**dict(row)) if row else None


def get_tools() -> list[Tool]:
    with database._conn() as conn:
        rows = conn.execute("SELECT * FROM tools WHERE deleted_at IS NULL ORDER BY name").fetchall()
    return [Tool(**dict(r)) for r in rows]


def get_tools_by_ids(ids: list[int]) -> list[Tool]:
    """Return Tool rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with database._conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tools WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: Tool(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete_tool(tool_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        conn.execute(
            "UPDATE tools SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), tool_id),
        )
        database._write_audit_log(conn, actor, "delete_tool", "tools", tool_id)
