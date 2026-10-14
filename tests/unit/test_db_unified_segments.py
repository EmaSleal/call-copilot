"""
Unit tests for the unified_segments view — a read-only wrapper over
`call_segments`, kept as its own view (rather than querying call_segments
directly) so a future second source can be unioned in without an API
change for callers (src/mcp/queries.py, src/tui/tabs/historial.py).
"""

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_unified_segments.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestUnifiedSegmentsViewMigration:
    def test_view_exists_after_init(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            views = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()}
        finally:
            conn.close()
        assert "unified_segments" in views

    def test_view_recreated_idempotently(self, patched_db):
        import src.db.database as db_module
        db_module.init_db()  # second run must not raise


class TestUnifiedSegmentsContent:
    def test_includes_call_segment_with_source(self, patched_db):
        from src.db.database import CallSegment
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="call idea")
        )

        results = patched_db.get_unified_segments()

        call_rows = [r for r in results if r.source == "call"]
        assert len(call_rows) == 1
        assert call_rows[0].text == "call idea"
        assert call_rows[0].session_id == call_session.id

    def test_preserves_category_id(self, patched_db):
        from src.db.database import CallSegment
        cat_id = patched_db.get_categories()[0].id

        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0,
                        text="call idea", category_id=cat_id)
        )

        results = patched_db.get_unified_segments()
        assert all(r.category_id == cat_id for r in results)

    def test_ordered_by_session_then_position(self, patched_db):
        from src.db.database import CallSegment
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=1, text="second")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="first")
        )

        results = patched_db.get_unified_segments()

        assert [r.text for r in results] == ["first", "second"]

    def test_filters_by_source(self, patched_db):
        from src.db.database import CallSegment
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="call idea")
        )

        call_only = patched_db.get_unified_segments(source="call")
        other_source = patched_db.get_unified_segments(source="nonexistent")

        assert [r.text for r in call_only] == ["call idea"]
        assert other_source == []

    def test_empty_when_no_segments(self, patched_db):
        assert patched_db.get_unified_segments() == []

    def test_filters_by_session_id_within_source(self, patched_db):
        """Two call sessions must not leak segments into each other's filtered result."""
        from src.db.database import CallSegment
        session_a = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/a.txt")
        session_b = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/b.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=session_a.id, sort_order=0, text="from A")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=session_b.id, sort_order=0, text="from B")
        )

        results = patched_db.get_unified_segments(source="call", session_id=session_a.id)

        assert [r.text for r in results] == ["from A"]
