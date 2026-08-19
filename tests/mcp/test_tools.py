"""
Unit tests for src/mcp/tools.py — async MCP tool handlers wrapping the
sync DAO/query layer via `asyncio.to_thread`, per sdd/mcp-server-read-only
Phase 2 (tasks 2.4-2.6).

Two styles, matching the existing tests/mcp/test_queries.py conventions:
- `test_search_content_tool_wraps_query` mocks `src.mcp.queries.search_content`
  directly, asserting the handler is a thin async wrapper (correct args in,
  correct result out, no data transformation of an already-dict result).
- The other three handlers are exercised against a real temp-SQLite DB via
  the same `patched_db` fixture used in test_queries.py, since they compose
  multiple DAO calls (get_session) or need to prove JSON-serializable dict
  conversion of dataclass rows (list_categories, list_tools_catalog).
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_mcp_tools.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestSearchContentTool:
    def test_search_content_tool_wraps_query(self):
        from src.mcp import tools

        fake_result = [
            {
                "session_id": 1, "source": "call", "session_title": "Call 1",
                "category_id": 2, "category_name": "Backend", "category_color": "#111111",
                "matched_text": "usamos Redis", "created_at": "2026-01-01T00:00:00",
            }
        ]

        with patch("src.mcp.queries.search_content", return_value=fake_result) as mocked:
            result = asyncio.run(
                tools.search_content(category_id=2, technology="Redis", source="call", limit=10, offset=0)
            )

        mocked.assert_called_once_with(
            category_id=2, technology="Redis", title_query=None, text_query=None,
            source="call", limit=10, offset=0,
        )
        assert result == fake_result
        # Every item must already be JSON-serializable (plain dict, no dataclass).
        assert isinstance(result[0], dict)

    def test_search_content_tool_default_args(self):
        from src.mcp import tools

        with patch("src.mcp.queries.search_content", return_value=[]) as mocked:
            result = asyncio.run(tools.search_content())

        mocked.assert_called_once_with(
            category_id=None, technology=None, title_query=None, text_query=None,
            source=None, limit=50, offset=0,
        )
        assert result == []


class TestListCategoriesTool:
    def test_list_categories_returns_json_serializable_dicts(self, patched_db):
        from src.mcp import tools

        parent = patched_db.create_category("Backend", "desc", color="#3b82f6")
        child = patched_db.create_category("Databases", "desc", parent_id=parent.id)

        results = asyncio.run(tools.list_categories())

        by_name = {r["name"]: r for r in results}
        assert isinstance(results, list)
        assert all(isinstance(r, dict) for r in results)
        assert by_name["Backend"]["parent_id"] is None
        assert by_name["Databases"]["parent_id"] == parent.id
        for field in ("id", "name", "description", "color", "parent_id"):
            assert field in by_name["Backend"]


class TestListToolsCatalogTool:
    def test_list_tools_catalog_no_filter_returns_all(self, patched_db):
        from src.db.database import Tool
        from src.mcp import tools

        patched_db.create_tool(Tool(id=None, name="Redis", normalized_name="redis"))
        patched_db.create_tool(Tool(id=None, name="PostgreSQL", normalized_name="postgresql"))

        results = asyncio.run(tools.list_tools_catalog())

        assert {r["name"] for r in results} == {"Redis", "PostgreSQL"}
        assert all(isinstance(r, dict) for r in results)

    def test_list_tools_catalog_filters_by_name_query_case_insensitive(self, patched_db):
        from src.db.database import Tool
        from src.mcp import tools

        patched_db.create_tool(Tool(id=None, name="Redis", normalized_name="redis"))
        patched_db.create_tool(Tool(id=None, name="PostgreSQL", normalized_name="postgresql"))
        patched_db.create_tool(Tool(id=None, name="RabbitMQ", normalized_name="rabbitmq"))

        results = asyncio.run(tools.list_tools_catalog(name_query="re"))

        # substring "re" matches "Redis" and "PostgreSQL" (case-insensitive), not "RabbitMQ"
        assert {r["name"] for r in results} == {"Redis", "PostgreSQL"}


class TestGetSessionTool:
    def test_get_session_returns_session_and_its_segments(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp import tools

        cs = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/x.txt", title="Call 1"
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="seg one")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="seg two")
        )
        # A different session/source must not leak into the result.
        other_cs = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/y.txt", title="Call 2"
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=other_cs.id, sort_order=0, text="unrelated")
        )

        result = asyncio.run(tools.get_session(session_id=cs.id, source="call"))

        assert isinstance(result, dict)
        assert "session" in result and "segments" in result
        assert result["session"]["id"] == cs.id
        assert result["session"]["source"] == "call"
        assert result["session"]["title"] == "Call 1"
        assert [s["text"] for s in result["segments"]] == ["seg one", "seg two"]
        assert all(isinstance(s, dict) for s in result["segments"])

    def test_get_session_unknown_id_returns_none_session_and_empty_segments(self, patched_db):
        from src.mcp import tools

        result = asyncio.run(tools.get_session(session_id=999999, source="call"))

        assert result["session"] is None
        assert result["segments"] == []
