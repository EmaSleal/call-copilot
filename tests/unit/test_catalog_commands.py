"""
Unit tests for the concrete catalog-maintenance commands (PR3a scope:
list_categories, list_tools, update_category, reassign_segment_category,
delete_category, delete_tool) registered by
src.agent.catalog_commands.register_all() into the generic registry
(src.agent.commands).

RED phase: src/agent/catalog_commands.py does not exist yet.
"""

import pytest


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_catalog_commands.db")
    db_module.init_db()
    return db_module


@pytest.fixture
def commands(patched_db, monkeypatch):
    """A clean registry per test, with the catalog commands registered."""
    from src.agent import commands as commands_module
    from src.agent import catalog_commands
    monkeypatch.setattr(commands_module, "_REGISTRY", {})
    catalog_commands.register_all()
    return commands_module


class TestRegisterAll:
    def test_registers_the_expected_commands_with_correct_kinds(self, commands):
        by_name = {c.name: c.kind for c in commands.all_commands()}
        assert by_name == {
            "list_categories": "read",
            "list_tools": "read",
            "update_category": "write",
            "reassign_segment_category": "write",
            "delete_category": "delete",
            "delete_tool": "delete",
        }

    def test_delete_commands_have_table_name_set(self, commands):
        assert commands.get_command("delete_category").table_name == "categories"
        assert commands.get_command("delete_tool").table_name == "tools"

    def test_every_command_has_a_valid_openai_tool_shape(self, commands):
        for tool in commands.openai_tools():
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert tool["function"]["parameters"]["type"] == "object"


class TestListCategories:
    def test_returns_categories_as_dicts(self, commands, patched_db):
        cat = patched_db.create_category("Backend", "APIs y servidores")

        result = commands.execute("list_categories", {})

        assert any(c["id"] == cat.id and c["name"] == "Backend" for c in result)

    def test_excludes_soft_deleted_categories(self, commands, patched_db):
        cat = patched_db.create_category("Temporal", "desc")
        patched_db.delete_category(cat.id)

        result = commands.execute("list_categories", {})

        assert all(c["id"] != cat.id for c in result)


class TestListTools:
    def test_returns_tools_as_dicts(self, commands, patched_db):
        from src.db.database import Tool

        tool = patched_db.create_tool(
            Tool(id=None, name="Deepgram", normalized_name="deepgram")
        )

        result = commands.execute("list_tools", {})

        assert any(t["id"] == tool.id and t["name"] == "Deepgram" for t in result)


class TestUpdateCategory:
    def test_updates_only_the_provided_fields(self, commands, patched_db):
        cat = patched_db.create_category("Backend", "desc original", color="#111111")

        commands.execute("update_category", {"id": cat.id, "description": "nueva desc"})

        updated = {c.id: c for c in patched_db.get_categories()}[cat.id]
        assert updated.name == "Backend"
        assert updated.description == "nueva desc"
        assert updated.color == "#111111"

    def test_unknown_id_raises_valueerror(self, commands, patched_db):
        with pytest.raises(ValueError):
            commands.execute("update_category", {"id": 999999, "name": "x"})


class TestReassignSegmentCategory:
    def test_video_source_updates_segment_via_db(self, commands, patched_db):
        from src.db.database import Segment

        cat = patched_db.create_category("Backend", "desc")
        session = patched_db.create_video_session(title="v1", url="http://x")
        seg = patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="hola")
        )

        commands.execute("reassign_segment_category", {
            "segment_id": seg.id, "category_id": cat.id, "source": "video",
        })

        updated = {s.id: s for s in patched_db.get_segments(session.id)}[seg.id]
        assert updated.category_id == cat.id

    def test_call_source_updates_call_segment_via_db(self, commands, patched_db):
        from src.db.database import CallSegment

        cat = patched_db.create_category("Backend", "desc")
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )

        commands.execute("reassign_segment_category", {
            "segment_id": seg_id, "category_id": cat.id, "source": "call",
        })

        updated = {s.id: s for s in patched_db.get_call_segments(cs.id)}[seg_id]
        assert updated.category_id == cat.id

    def test_unknown_source_raises_valueerror(self, commands, patched_db):
        with pytest.raises(ValueError):
            commands.execute("reassign_segment_category", {
                "segment_id": 1, "category_id": 1, "source": "carrier_pigeon",
            })


class TestDeleteCategoryCommand:
    def test_queues_instead_of_deleting_immediately(self, commands, patched_db):
        cat = patched_db.create_category("Backend", "desc")

        commands.execute("delete_category", {"row_id": cat.id, "reason": "sin uso"})

        assert cat.id in {c.id for c in patched_db.get_categories()}
        pending = patched_db.get_pending_actions()
        assert len(pending) == 1
        assert pending[0].action == "delete_category"
        assert pending[0].row_id == cat.id

    def test_approval_actually_deletes_via_db_with_agent_actor(self, commands, patched_db):
        cat = patched_db.create_category("Backend", "desc")
        commands.execute("delete_category", {"row_id": cat.id})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.approve_pending_action(pending_id, resolved_by="human")

        assert cat.id not in {c.id for c in patched_db.get_categories()}


class TestDeleteToolCommand:
    def test_queues_instead_of_deleting_immediately(self, commands, patched_db):
        from src.db.database import Tool

        tool = patched_db.create_tool(Tool(id=None, name="Deepgram", normalized_name="deepgram"))

        commands.execute("delete_tool", {"row_id": tool.id, "reason": "duplicado"})

        assert tool.id in {t.id for t in patched_db.get_tools()}
        pending = patched_db.get_pending_actions()
        assert len(pending) == 1
        assert pending[0].action == "delete_tool"
        assert pending[0].row_id == tool.id

    def test_approval_actually_deletes_via_db(self, commands, patched_db):
        from src.db.database import Tool

        tool = patched_db.create_tool(Tool(id=None, name="Deepgram", normalized_name="deepgram"))
        commands.execute("delete_tool", {"row_id": tool.id})
        pending_id = patched_db.get_pending_actions()[0].id

        commands.approve_pending_action(pending_id, resolved_by="human")

        assert tool.id not in {t.id for t in patched_db.get_tools()}
