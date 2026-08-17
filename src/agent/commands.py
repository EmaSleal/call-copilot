"""
Command layer for AI-agent-operable CRUD over the DAO — a curated,
classified (read/write/delete) registry of named commands exposed to the
OpenAI tool-calling loop (src/agent/maintenance.py, PR3b). Concrete
catalog-maintenance commands live in src/agent/catalog_commands.py; this
module is only the generic registration/dispatch mechanism.

Read/write commands execute immediately when the agent calls them via
execute(). Delete commands never execute directly — execute() queues a
PendingAction instead (D2: agent writes run autonomously, deletes always
wait for a human). The delete command's handler only runs later, from
approve_pending_action(), once a human approves it (PR3c wires that to a
TUI screen).
"""

from dataclasses import dataclass
from typing import Any, Callable, Literal

import src.db.database as db

Kind = Literal["read", "write", "delete"]


@dataclass
class Command:
    name: str
    kind: Kind
    description: str
    parameters: dict  # JSON schema, OpenAI tool-calling "parameters" shape
    handler: Callable[..., Any]
    table_name: str = ""  # required for kind="delete" — the pending_actions.table_name

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, Command] = {}


def register(cmd: Command) -> None:
    _REGISTRY[cmd.name] = cmd


def get_command(name: str) -> Command | None:
    return _REGISTRY.get(name)


def all_commands() -> list[Command]:
    return list(_REGISTRY.values())


def openai_tools() -> list[dict]:
    return [cmd.to_openai_tool() for cmd in all_commands()]


def execute(name: str, arguments: dict, actor: str = "agent") -> Any:
    cmd = get_command(name)
    if cmd is None:
        raise KeyError(f"Unknown command: {name}")
    if cmd.kind == "delete":
        pending = db.create_pending_action(
            actor=actor,
            action=cmd.name,
            table_name=cmd.table_name,
            row_id=arguments["row_id"],
            reason=arguments.get("reason", ""),
        )
        return {"status": "queued_for_approval", "pending_action_id": pending.id}
    return cmd.handler(**arguments)


def approve_pending_action(pending_id: int, resolved_by: str = "human") -> None:
    pending = {p.id: p for p in db.get_pending_actions(status="pending")}.get(pending_id)
    if pending is None:
        raise ValueError(f"no pending action with id {pending_id}")
    cmd = get_command(pending.action)
    if cmd is None:
        raise KeyError(f"Unknown command for pending action: {pending.action}")
    cmd.handler(pending.row_id)
    db.resolve_pending_action(pending_id, status="approved", resolved_by=resolved_by)


def reject_pending_action(pending_id: int, resolved_by: str = "human") -> None:
    db.resolve_pending_action(pending_id, status="rejected", resolved_by=resolved_by)
