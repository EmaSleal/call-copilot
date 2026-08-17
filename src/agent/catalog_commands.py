"""
Concrete catalog-maintenance commands — the tool surface the post-call
maintenance agent (src/agent/maintenance.py, PR3b) gets to inspect and fix
categories/tools after a call. Deliberately narrow (6 commands, not every
DAO function): the agent composes these primitives itself (e.g. reassign
every segment off a category, then delete_category it) rather than being
handed a bespoke "merge_categories" command.

register_all() populates src.agent.commands's registry — call it once
before running the maintenance loop (or, in tests, once per clean
registry fixture).
"""

import src.db.database as db
from src.agent.commands import Command, register


def _list_categories() -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "description": c.description, "color": c.color, "parent_id": c.parent_id}
        for c in db.get_categories()
    ]


def _list_tools() -> list[dict]:
    return [
        {"id": t.id, "name": t.name, "category": t.category, "description": t.description}
        for t in db.get_tools()
    ]


def _update_category(id: int, name: str | None = None, description: str | None = None, color: str | None = None) -> dict:
    current = {c.id: c for c in db.get_categories()}.get(id)
    if current is None:
        raise ValueError(f"category {id} not found")
    db.update_category(
        id,
        name if name is not None else current.name,
        description if description is not None else current.description,
        color if color is not None else current.color,
        current.parent_id,
    )
    return {"id": id, "status": "updated"}


def _reassign_segment_category(segment_id: int, category_id: int, source: str) -> dict:
    if source == "video":
        db.update_segment_category(segment_id, category_id)
    elif source == "call":
        db.update_call_segment_category(segment_id, category_id)
    else:
        raise ValueError(f"unknown source: {source!r} (expected 'video' or 'call')")
    return {"segment_id": segment_id, "category_id": category_id, "source": source, "status": "updated"}


def _delete_category(row_id: int) -> None:
    db.delete_category(row_id, actor="agent")


def _delete_tool(row_id: int) -> None:
    db.delete_tool(row_id, actor="agent")


def register_all() -> None:
    register(Command(
        name="list_categories", kind="read",
        description="List every non-deleted category (id, name, description, color, parent_id).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_list_categories,
    ))
    register(Command(
        name="list_tools", kind="read",
        description="List every non-deleted tool in the Tools Catalog (id, name, category, description).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_list_tools,
    ))
    register(Command(
        name="update_category", kind="write",
        description="Update a category's name/description/color. Omitted fields are left unchanged.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "color": {"type": "string"},
            },
            "required": ["id"],
        },
        handler=_update_category,
    ))
    register(Command(
        name="reassign_segment_category", kind="write",
        description="Move a video or call segment to a different category.",
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {"type": "integer"},
                "category_id": {"type": "integer"},
                "source": {"type": "string", "enum": ["video", "call"]},
            },
            "required": ["segment_id", "category_id", "source"],
        },
        handler=_reassign_segment_category,
    ))
    register(Command(
        name="delete_category", kind="delete", table_name="categories",
        description="Propose deleting a category (queued for human approval, never executes immediately).",
        parameters={
            "type": "object",
            "properties": {
                "row_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["row_id"],
        },
        handler=_delete_category,
    ))
    register(Command(
        name="delete_tool", kind="delete", table_name="tools",
        description="Propose deleting a tool (queued for human approval, never executes immediately).",
        parameters={
            "type": "object",
            "properties": {
                "row_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["row_id"],
        },
        handler=_delete_tool,
    ))
