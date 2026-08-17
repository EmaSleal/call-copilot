"""DAOs — Pending Actions (agent-proposed deletes awaiting human approval)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db import database


@dataclass
class PendingAction:
    """An agent-proposed delete awaiting human approval (D2: agent writes
    run autonomously, deletes always wait for a human)."""
    id: Optional[int]
    actor: str
    action: str
    table_name: str
    row_id: int
    reason: str = ""
    status: str = "pending"  # pending | approved | rejected
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


def create_pending_action(
    actor: str, action: str, table_name: str, row_id: int, reason: str = ""
) -> PendingAction:
    pa = PendingAction(
        id=None, actor=actor, action=action, table_name=table_name, row_id=row_id, reason=reason
    )
    with database._conn() as conn:
        cur = conn.execute(
            """INSERT INTO pending_actions
               (actor, action, table_name, row_id, reason, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pa.actor, pa.action, pa.table_name, pa.row_id, pa.reason, pa.status, pa.created_at)
        )
        pa.id = cur.lastrowid
    return pa


def get_pending_actions(status: str = "pending") -> list[PendingAction]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions WHERE status=? ORDER BY created_at", (status,)
        ).fetchall()
    return [PendingAction(**dict(r)) for r in rows]


def resolve_pending_action(pending_id: int, status: str, resolved_by: str) -> None:
    """`status` is the caller's decision: "approved" or "rejected". Only
    updates bookkeeping — actually executing an approved delete is the
    command layer's job (src.agent.commands), since only it knows how to
    map an action name back to the real DAO delete function."""
    with database._conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (status, datetime.now().isoformat(), resolved_by, pending_id),
        )
