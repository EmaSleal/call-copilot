"""
Unit tests for the agent command registry (src/agent/commands.py) — the
generic read/write/delete dispatch mechanism the OpenAI tool-calling loop
(PR3b) will call into. Tested here against ad-hoc dummy commands, decoupled
from whatever concrete catalog-maintenance commands PR3a also registers
(see test_catalog_commands.py for those).

Delete-kind commands never execute their handler when the agent calls
them — execute() always queues a PendingAction instead (D2: agent writes
run autonomously, deletes always wait for a human). The handler only runs
later, from approve_pending_action(), once a human approves it.

RED phase: src/agent/commands.py does not exist yet.
"""

import pytest
from pathlib import Path


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_agent_commands.db")
    db_module.init_db()
    return db_module


@pytest.fixture
def commands(patched_db, monkeypatch):
    """A clean registry per test — _REGISTRY is module-level global state."""
    from src.agent import commands as commands_module
    monkeypatch.setattr(commands_module, "_REGISTRY", {})
    return commands_module


class TestRegisterAndLookup:
    def test_get_command_returns_registered_command(self, commands):
        cmd = commands.Command(
            name="ping", kind="read", description="ping", parameters={"type": "object", "properties": {}},
            handler=lambda: "pong",
        )
        commands.register(cmd)

        assert commands.get_command("ping") is cmd

    def test_get_command_returns_none_for_unknown_name(self, commands):
        assert commands.get_command("nope") is None

    def test_all_commands_returns_every_registered_command(self, commands):
        a = commands.Command(
            name="a", kind="read", description="a", parameters={"type": "object", "properties": {}},
            handler=lambda: None,
        )
        b = commands.Command(
            name="b", kind="write", description="b", parameters={"type": "object", "properties": {}},
            handler=lambda: None,
        )
        commands.register(a)
        commands.register(b)

        assert {c.name for c in commands.all_commands()} == {"a", "b"}


class TestToOpenaiTool:
    def test_shape_matches_openai_function_tool_format(self, commands):
        cmd = commands.Command(
            name="list_categories", kind="read", description="List categories.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda: [],
        )

        tool = cmd.to_openai_tool()

        assert tool == {
            "type": "function",
            "function": {
                "name": "list_categories",
                "description": "List categories.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def test_openai_tools_returns_one_entry_per_registered_command(self, commands):
        commands.register(commands.Command(
            name="a", kind="read", description="a", parameters={"type": "object", "properties": {}},
            handler=lambda: None,
        ))
        commands.register(commands.Command(
            name="b", kind="write", description="b", parameters={"type": "object", "properties": {}},
            handler=lambda: None,
        ))

        tools = commands.openai_tools()

        assert {t["function"]["name"] for t in tools} == {"a", "b"}


class TestExecuteReadWrite:
    def test_read_command_calls_handler_with_arguments_and_returns_result(self, commands):
        commands.register(commands.Command(
            name="double", kind="read", description="doubles a number",
            parameters={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
            handler=lambda n: n * 2,
        ))

        result = commands.execute("double", {"n": 21})

        assert result == 42

    def test_write_command_calls_handler(self, commands):
        calls = []
        commands.register(commands.Command(
            name="record", kind="write", description="records a call",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=lambda x: calls.append(x) or {"status": "ok"},
        ))

        result = commands.execute("record", {"x": "hola"})

        assert calls == ["hola"]
        assert result == {"status": "ok"}

    def test_unknown_command_raises_keyerror(self, commands):
        with pytest.raises(KeyError):
            commands.execute("nope", {})


class TestExecuteDelete:
    def test_delete_command_does_not_call_handler(self, commands):
        calls = []
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: calls.append(row_id),
            table_name="things",
        ))

        commands.execute("delete_thing", {"row_id": 7})

        assert calls == []

    def test_delete_command_queues_a_pending_action(self, commands, patched_db):
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: None,
            table_name="things",
        ))

        commands.execute("delete_thing", {"row_id": 7, "reason": "duplicate"}, actor="agent")

        pending = patched_db.get_pending_actions()
        assert len(pending) == 1
        assert pending[0].actor == "agent"
        assert pending[0].action == "delete_thing"
        assert pending[0].table_name == "things"
        assert pending[0].row_id == 7
        assert pending[0].reason == "duplicate"

    def test_delete_command_returns_queued_status_with_pending_action_id(self, commands, patched_db):
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: None,
            table_name="things",
        ))

        result = commands.execute("delete_thing", {"row_id": 7})

        pending = patched_db.get_pending_actions()
        assert result == {"status": "queued_for_approval", "pending_action_id": pending[0].id}


class TestApprovePendingAction:
    def test_calls_the_commands_handler_with_the_row_id(self, commands, patched_db):
        calls = []
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: calls.append(row_id),
            table_name="things",
        ))
        commands.execute("delete_thing", {"row_id": 7})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.approve_pending_action(pending_id, resolved_by="human")

        assert calls == [7]

    def test_marks_the_pending_action_approved(self, commands, patched_db):
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: None,
            table_name="things",
        ))
        commands.execute("delete_thing", {"row_id": 7})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.approve_pending_action(pending_id, resolved_by="human")

        approved = {p.id: p for p in patched_db.get_pending_actions(status="approved")}
        assert pending_id in approved
        assert approved[pending_id].resolved_by == "human"

    def test_unknown_pending_id_raises_valueerror(self, commands, patched_db):
        with pytest.raises(ValueError):
            commands.approve_pending_action(999999, resolved_by="human")


class TestRejectPendingAction:
    def test_does_not_call_the_handler(self, commands, patched_db):
        calls = []
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: calls.append(row_id),
            table_name="things",
        ))
        commands.execute("delete_thing", {"row_id": 7})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.reject_pending_action(pending_id, resolved_by="human")

        assert calls == []

    def test_marks_the_pending_action_rejected(self, commands, patched_db):
        commands.register(commands.Command(
            name="delete_thing", kind="delete", description="deletes a thing",
            parameters={"type": "object", "properties": {"row_id": {"type": "integer"}}, "required": ["row_id"]},
            handler=lambda row_id: None,
            table_name="things",
        ))
        commands.execute("delete_thing", {"row_id": 7})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.reject_pending_action(pending_id, resolved_by="human")

        rejected = {p.id: p for p in patched_db.get_pending_actions(status="rejected")}
        assert pending_id in rejected
        assert rejected[pending_id].resolved_by == "human"
