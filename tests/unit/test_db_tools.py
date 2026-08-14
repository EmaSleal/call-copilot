"""
Unit tests for PR1 — Tools Catalog: schema, dataclasses, DAOs.

TDD RED phase — tests written against interfaces that do not yet exist.

Authoritative design (sdd/tools-catalog):
  - New `tools` table: id, name, normalized_name (UNIQUE), category,
    description, summary, tags, created_at
  - New `tool_mentions` table: id, tool_id (FK -> tools.id), call_session_id,
    context_snippet, created_at
  - `Tool`, `ToolMention` dataclasses
  - `normalize_tool_name(name) -> str`
  - `create_tool(t: Tool) -> Tool`
  - `find_tool_by_name(name: str) -> Optional[Tool]`
  - `get_tools() -> list[Tool]`
  - `get_tools_by_ids(ids: list[int]) -> list[Tool]` (preserves caller order)
  - `save_tool_mention(m: ToolMention) -> int`
  - `get_tool_mentions(tool_id: int) -> list[ToolMention]` (unlimited retention)
"""

import sqlite3
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_tools.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    """Initialize DB against a temp file so every test is isolated."""
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


# ─────────────────────────────────────────────────────────────
# Phase 1 — Schema: tools / tool_mentions tables
# ─────────────────────────────────────────────────────────────

class TestToolsSchema:
    def test_tools_table_exists_after_init(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert "tools" in tables

    def test_tools_schema_columns(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(tools)").fetchall()}
        finally:
            conn.close()
        assert {
            "id", "name", "normalized_name", "category",
            "description", "summary", "tags", "created_at",
        } <= cols

    def test_tools_normalized_name_is_unique(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            indexes = conn.execute("PRAGMA index_list(tools)").fetchall()
            unique_cols = set()
            for idx in indexes:
                if idx[2]:  # unique flag
                    for col in conn.execute(f"PRAGMA index_info({idx[1]})").fetchall():
                        unique_cols.add(col[2])
        finally:
            conn.close()
        assert "normalized_name" in unique_cols

    def test_tool_mentions_table_exists_after_init(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert "tool_mentions" in tables

    def test_tool_mentions_schema_columns(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(tool_mentions)").fetchall()}
        finally:
            conn.close()
        assert {"id", "tool_id", "call_session_id", "context_snippet", "created_at"} <= cols

    def test_init_db_idempotent_for_tools_tables(self, patched_db, db_path):
        """Running init_db() twice must not raise (IDF NOT EXISTS)."""
        import src.db.database as db_module
        db_module.init_db()
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert {"tools", "tool_mentions"} <= tables


# ─────────────────────────────────────────────────────────────
# Phase 1 — Dataclasses
# ─────────────────────────────────────────────────────────────

class TestToolDataclasses:
    def test_tool_instantiates_with_defaults(self, patched_db):
        from src.db.database import Tool
        t = Tool(id=None, name="Chroma", normalized_name="chroma")
        assert t.name == "Chroma"
        assert t.normalized_name == "chroma"
        assert t.category == ""
        assert t.description == ""
        assert t.summary == ""
        assert t.tags == ""
        assert t.created_at

    def test_tool_mention_instantiates_with_defaults(self, patched_db):
        from src.db.database import ToolMention
        m = ToolMention(id=None, tool_id=1, call_session_id=2)
        assert m.tool_id == 1
        assert m.call_session_id == 2
        assert m.context_snippet == ""
        assert m.created_at


# ─────────────────────────────────────────────────────────────
# Phase 2 — normalize_tool_name / create_tool / find_tool_by_name
# ─────────────────────────────────────────────────────────────

class TestNormalizeToolName:
    def test_normalize_lowercases_strips_and_drops_trailing_punct(self, patched_db):
        assert patched_db.normalize_tool_name("Chroma DB.") == "chroma db"

    def test_normalize_collapses_internal_whitespace(self, patched_db):
        assert patched_db.normalize_tool_name("Chroma   DB") == "chroma db"

    def test_normalize_strips_leading_trailing_whitespace(self, patched_db):
        assert patched_db.normalize_tool_name("  Deepgram  ") == "deepgram"


class TestCreateTool:
    def test_create_tool_sets_id(self, patched_db):
        from src.db.database import Tool
        t = Tool(id=None, name="Deepgram", normalized_name="deepgram")
        created = patched_db.create_tool(t)
        assert created.id is not None
        assert isinstance(created.id, int)

    def test_create_tool_persists_row(self, patched_db, db_path):
        from src.db.database import Tool
        t = Tool(id=None, name="Deepgram", normalized_name="deepgram", category="STT")
        patched_db.create_tool(t)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT name, normalized_name, category FROM tools WHERE normalized_name='deepgram'"
            ).fetchone()
        finally:
            conn.close()
        assert row == ("Deepgram", "deepgram", "STT")


class TestFindToolByName:
    def test_find_tool_by_name_hit_normalizes_input(self, patched_db):
        from src.db.database import Tool
        patched_db.create_tool(Tool(id=None, name="Chroma DB", normalized_name="chroma db"))
        found = patched_db.find_tool_by_name("Chroma DB.")
        assert found is not None
        assert found.normalized_name == "chroma db"

    def test_find_tool_by_name_miss_returns_none(self, patched_db):
        found = patched_db.find_tool_by_name("Nonexistent Tool")
        assert found is None


# ─────────────────────────────────────────────────────────────
# Phase 3 — get_tools / get_tools_by_ids / save_tool_mention / get_tool_mentions
# ─────────────────────────────────────────────────────────────

class TestGetTools:
    def test_get_tools_returns_all(self, patched_db):
        from src.db.database import Tool
        patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma"))
        patched_db.create_tool(Tool(id=None, name="Deepgram", normalized_name="deepgram"))
        tools = patched_db.get_tools()
        assert len(tools) == 2


class TestGetToolsByIds:
    def test_get_tools_by_ids_preserves_caller_order(self, patched_db):
        from src.db.database import Tool
        t1 = patched_db.create_tool(Tool(id=None, name="A", normalized_name="a"))
        t2 = patched_db.create_tool(Tool(id=None, name="B", normalized_name="b"))
        t3 = patched_db.create_tool(Tool(id=None, name="C", normalized_name="c"))

        result = patched_db.get_tools_by_ids([t3.id, t1.id, t2.id])

        assert [r.id for r in result] == [t3.id, t1.id, t2.id]

    def test_get_tools_by_ids_empty_list_returns_empty(self, patched_db):
        assert patched_db.get_tools_by_ids([]) == []

    def test_get_tools_by_ids_skips_missing_ids(self, patched_db):
        from src.db.database import Tool
        t1 = patched_db.create_tool(Tool(id=None, name="A", normalized_name="a"))
        result = patched_db.get_tools_by_ids([t1.id, 9999])
        assert [r.id for r in result] == [t1.id]


class TestToolMentions:
    def test_save_tool_mention_returns_id(self, patched_db):
        from src.db.database import Tool, ToolMention
        t = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma"))
        m = ToolMention(id=None, tool_id=t.id, call_session_id=1, context_snippet="we used chroma")
        returned_id = patched_db.save_tool_mention(m)
        assert isinstance(returned_id, int)
        assert returned_id > 0

    def test_get_tool_mentions_returns_matching_rows(self, patched_db):
        from src.db.database import Tool, ToolMention
        t = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma"))
        patched_db.save_tool_mention(ToolMention(id=None, tool_id=t.id, call_session_id=1))
        patched_db.save_tool_mention(ToolMention(id=None, tool_id=t.id, call_session_id=2))

        mentions = patched_db.get_tool_mentions(t.id)

        assert len(mentions) == 2

    def test_get_tool_mentions_retains_51_plus_rows_unpruned(self, patched_db):
        """Unlimited retention — no cap/limit clause on mention queries."""
        from src.db.database import Tool, ToolMention
        t = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma"))
        for i in range(51):
            patched_db.save_tool_mention(
                ToolMention(id=None, tool_id=t.id, call_session_id=i)
            )

        mentions = patched_db.get_tool_mentions(t.id)

        assert len(mentions) == 51
