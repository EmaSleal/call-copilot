"""
Unit tests for soft-delete (deleted_at column) + audit_log migration.

PR1 covered delete_category/delete_video_session (deleted_at + audit_log
migration for all 7 tables, but read filtering only for categories/
video_sessions/segments). PR2 (this addition) adds the delete functions
that didn't exist yet for call_sessions, call_segments, tools and
tool_mentions, following the same soft-delete + audit log pattern.
"""

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_soft_delete.db"


@pytest.fixture
def patched_db(db_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


TABLES_WITH_DELETED_AT = [
    "categories", "video_sessions", "segments",
    "call_sessions", "call_segments", "tools", "tool_mentions",
]


class TestDeletedAtMigration:
    @pytest.mark.parametrize("table", TABLES_WITH_DELETED_AT)
    def test_deleted_at_column_exists_and_nullable(self, patched_db, db_path, table):
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        finally:
            conn.close()
        col = next((r for r in rows if r[1] == "deleted_at"), None)
        assert col is not None, f"{table}.deleted_at missing"
        assert col[3] == 0, f"{table}.deleted_at must be nullable (notnull=0)"

    def test_migrate_is_idempotent_on_preexisting_db(self, patched_db, db_path):
        import src.db.database as db_module
        db_module.init_db()
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        finally:
            conn.close()
        assert "deleted_at" in col_names


class TestAuditLogTable:
    def test_audit_log_table_exists_with_expected_columns(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        finally:
            conn.close()
        assert {"id", "actor", "action", "table_name", "row_id", "details", "created_at"} <= col_names


def _audit_rows(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]
    finally:
        conn.close()


class TestDeleteCategorySoftDelete:
    def test_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        cat = patched_db.create_category("Categoría Test", "desc")
        patched_db.delete_category(cat.id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM categories WHERE id=?", (cat.id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_categories(self, patched_db):
        cat = patched_db.create_category("Categoría Test", "desc")
        patched_db.delete_category(cat.id)
        assert cat.id not in {c.id for c in patched_db.get_categories()}

    def test_still_unassigns_referencing_segments(self, patched_db):
        """FK-cleanup behavior must be preserved under soft-delete."""
        from src.db.database import CallSegment

        cat = patched_db.create_category("Categoría Test", "desc")
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea", category_id=cat.id)
        )

        patched_db.delete_category(cat.id)

        results = {s.id: s for s in patched_db.get_call_segments(cs.id)}
        assert results[seg_id].category_id is None

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        cat = patched_db.create_category("Categoría Test", "desc")
        patched_db.delete_category(cat.id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_category"
        assert entries[0]["table_name"] == "categories"
        assert entries[0]["row_id"] == cat.id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        cat = patched_db.create_category("Categoría Test", "desc")
        patched_db.delete_category(cat.id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"


class TestDeleteVideoSessionSoftDelete:
    def test_session_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.delete_video_session(session.id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM video_sessions WHERE id=?", (session.id,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_video_sessions(self, patched_db):
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.delete_video_session(session.id)
        assert session.id not in {s.id for s in patched_db.get_video_sessions()}

    def test_child_segments_soft_deleted_and_excluded_from_get_segments(self, patched_db, db_path):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v1", url="http://x")
        seg = patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="hola")
        )

        patched_db.delete_video_session(session.id)

        assert patched_db.get_segments(session.id) == []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM segments WHERE id=?", (seg.id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.delete_video_session(session.id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_video_session"
        assert entries[0]["table_name"] == "video_sessions"
        assert entries[0]["row_id"] == session.id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.delete_video_session(session.id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"


class TestSegmentReadFiltersExcludeSoftDeleted:
    def test_get_segments_by_category_excludes_soft_deleted(self, patched_db):
        from src.db.database import Segment

        cat = patched_db.create_category("Cat", "desc")
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="a", category_id=cat.id)
        )
        patched_db.delete_video_session(session.id)

        assert patched_db.get_segments_by_category(session.id, cat.id) == []

    def test_get_segments_by_category_global_excludes_soft_deleted(self, patched_db):
        from src.db.database import Segment

        cat = patched_db.create_category("Cat", "desc")
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="a", category_id=cat.id)
        )
        patched_db.delete_video_session(session.id)

        assert patched_db.get_segments_by_category_global(cat.id) == []

    def test_get_segments_by_ids_excludes_soft_deleted(self, patched_db):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v1", url="http://x")
        seg = patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="a")
        )
        patched_db.delete_video_session(session.id)

        assert patched_db.get_segments_by_ids([seg.id]) == []

    def test_search_segments_excludes_soft_deleted(self, patched_db):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="buscame")
        )
        patched_db.delete_video_session(session.id)

        assert patched_db.search_segments("buscame") == []


class TestUnifiedViewsExcludeSoftDeleted:
    def test_unified_segments_excludes_soft_deleted_video_segment(self, patched_db):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v1", url="http://x")
        seg = patched_db.save_segment(
            Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="a")
        )
        patched_db.delete_video_session(session.id)

        ids = {r.id for r in patched_db.get_unified_segments(source="video")}
        assert seg.id not in ids

    def test_unified_sessions_excludes_soft_deleted_video_session(self, patched_db):
        session = patched_db.create_video_session(title="v1", url="http://x")
        patched_db.delete_video_session(session.id)

        ids = {r.id for r in patched_db.get_unified_sessions() if r.source == "video"}
        assert session.id not in ids


# ─────────────────────────────────────────────────────────────
# PR2 — delete functions that didn't exist yet: call_sessions,
# call_segments, tools, tool_mentions. Same soft-delete + audit log
# pattern as delete_category/delete_video_session (PR1).
# ─────────────────────────────────────────────────────────────

def _make_tool(patched_db, name="Deepgram"):
    from src.db.database import Tool
    return patched_db.create_tool(
        Tool(id=None, name=name, normalized_name=patched_db.normalize_tool_name(name))
    )


class TestDeleteCallSession:
    def test_session_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.delete_call_session(cs.id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM call_sessions WHERE id=?", (cs.id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_call_sessions(self, patched_db):
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.delete_call_session(cs.id)
        assert cs.id not in {s.id for s in patched_db.get_call_sessions()}

    def test_child_call_segments_soft_deleted_and_excluded(self, patched_db, db_path):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )

        patched_db.delete_call_session(cs.id)

        assert patched_db.get_call_segments(cs.id) == []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM call_segments WHERE id=?", (seg_id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.delete_call_session(cs.id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_call_session"
        assert entries[0]["table_name"] == "call_sessions"
        assert entries[0]["row_id"] == cs.id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.delete_call_session(cs.id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"


class TestDeleteCallSegment:
    def test_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )
        patched_db.delete_call_segment(seg_id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM call_segments WHERE id=?", (seg_id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_call_segments_without_affecting_siblings(self, patched_db):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg1 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="uno")
        )
        seg2 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="dos")
        )

        patched_db.delete_call_segment(seg1)

        remaining = {s.id for s in patched_db.get_call_segments(cs.id)}
        assert remaining == {seg2}

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )
        patched_db.delete_call_segment(seg_id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_call_segment"
        assert entries[0]["table_name"] == "call_segments"
        assert entries[0]["row_id"] == seg_id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )
        patched_db.delete_call_segment(seg_id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"


class TestDeleteTool:
    def test_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        tool = _make_tool(patched_db)
        patched_db.delete_tool(tool.id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM tools WHERE id=?", (tool.id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_tools(self, patched_db):
        tool = _make_tool(patched_db)
        patched_db.delete_tool(tool.id)
        assert tool.id not in {t.id for t in patched_db.get_tools()}

    def test_excluded_from_get_tools_by_ids(self, patched_db):
        tool = _make_tool(patched_db)
        patched_db.delete_tool(tool.id)
        assert patched_db.get_tools_by_ids([tool.id]) == []

    def test_excluded_from_find_tool_by_name(self, patched_db):
        tool = _make_tool(patched_db, name="Deepgram")
        patched_db.delete_tool(tool.id)
        assert patched_db.find_tool_by_name("Deepgram") is None

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        tool = _make_tool(patched_db)
        patched_db.delete_tool(tool.id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_tool"
        assert entries[0]["table_name"] == "tools"
        assert entries[0]["row_id"] == tool.id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        tool = _make_tool(patched_db)
        patched_db.delete_tool(tool.id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"


class TestDeleteToolMention:
    def test_row_still_exists_with_deleted_at_set(self, patched_db, db_path):
        from src.db.database import ToolMention

        tool = _make_tool(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        mention_id = patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=tool.id, call_session_id=cs.id, context_snippet="usamos Deepgram")
        )

        patched_db.delete_tool_mention(mention_id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM tool_mentions WHERE id=?", (mention_id,)).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_excluded_from_get_tool_mentions_without_affecting_siblings(self, patched_db):
        from src.db.database import ToolMention

        tool = _make_tool(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        m1 = patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=tool.id, call_session_id=cs.id, context_snippet="uno")
        )
        m2 = patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=tool.id, call_session_id=cs.id, context_snippet="dos")
        )

        patched_db.delete_tool_mention(m1)

        remaining = {m.id for m in patched_db.get_tool_mentions(tool.id)}
        assert remaining == {m2}

    def test_writes_audit_log_entry_with_default_human_actor(self, patched_db, db_path):
        from src.db.database import ToolMention

        tool = _make_tool(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        mention_id = patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=tool.id, call_session_id=cs.id, context_snippet="algo")
        )
        patched_db.delete_tool_mention(mention_id)

        entries = _audit_rows(db_path)
        assert len(entries) == 1
        assert entries[0]["actor"] == "human"
        assert entries[0]["action"] == "delete_tool_mention"
        assert entries[0]["table_name"] == "tool_mentions"
        assert entries[0]["row_id"] == mention_id

    def test_accepts_explicit_actor(self, patched_db, db_path):
        from src.db.database import ToolMention

        tool = _make_tool(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        mention_id = patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=tool.id, call_session_id=cs.id, context_snippet="algo")
        )
        patched_db.delete_tool_mention(mention_id, actor="agent")

        entries = _audit_rows(db_path)
        assert entries[0]["actor"] == "agent"
