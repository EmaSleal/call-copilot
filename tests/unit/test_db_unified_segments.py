"""
Unit tests for the unified_segments view — a read-only SQL union of
`segments` (video) and `call_segments` (call), sharing the same
`categories` table but keeping their own source tables intact.
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
    def test_includes_video_segment_with_source(self, patched_db):
        from src.db.database import Segment
        video_session = patched_db.create_video_session(title="v", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=1.0, end_s=2.0, text="video idea")
        )

        results = patched_db.get_unified_segments()

        video_rows = [r for r in results if r.source == "video"]
        assert len(video_rows) == 1
        assert video_rows[0].text == "video idea"
        assert video_rows[0].session_id == video_session.id

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

    def test_preserves_category_id_from_both_sources(self, patched_db):
        from src.db.database import Segment, CallSegment
        cat_id = patched_db.get_categories()[0].id

        video_session = patched_db.create_video_session(title="v", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0,
                    text="video idea", category_id=cat_id)
        )
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
        from src.db.database import Segment, CallSegment
        video_session = patched_db.create_video_session(title="v", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="video idea")
        )
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="call idea")
        )

        video_only = patched_db.get_unified_segments(source="video")
        call_only = patched_db.get_unified_segments(source="call")

        assert [r.text for r in video_only] == ["video idea"]
        assert [r.text for r in call_only] == ["call idea"]

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

    def test_filters_by_source_and_session_id_across_id_collision(self, patched_db):
        """
        video_sessions.id and call_sessions.id are independent sequences and can
        collide numerically — filtering must require BOTH source and session_id.
        """
        from src.db.database import Segment, CallSegment
        video_session = patched_db.create_video_session(title="v", url="http://x")
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        # Force an id collision regardless of insertion order in this run.
        assert video_session.id == call_session.id

        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="video idea")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="call idea")
        )

        video_result = patched_db.get_unified_segments(source="video", session_id=video_session.id)
        call_result = patched_db.get_unified_segments(source="call", session_id=call_session.id)

        assert [r.text for r in video_result] == ["video idea"]
        assert [r.text for r in call_result] == ["call idea"]
