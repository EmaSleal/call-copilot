"""
Unit tests for get_segments_by_ids / get_call_segments_by_ids — bulk
lookups by id, order-preserving (mirrors get_tools_by_ids' shape), needed
to join semantic search results (composite "<source>:<id>" from
SegmentsSearchStore) back to full SQL rows.
"""

import pytest
from pathlib import Path


@pytest.fixture
def patched_db(tmp_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_segments_by_ids.db")
    db_module.init_db()
    return db_module


class TestGetSegmentsByIds:
    def test_returns_rows_preserving_caller_order(self, patched_db):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v", url="http://x")
        s1 = patched_db.save_segment(Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="one"))
        s2 = patched_db.save_segment(Segment(id=None, session_id=session.id, start_s=1.0, end_s=2.0, text="two"))
        s3 = patched_db.save_segment(Segment(id=None, session_id=session.id, start_s=2.0, end_s=3.0, text="three"))

        results = patched_db.get_segments_by_ids([s3.id, s1.id])

        assert [r.id for r in results] == [s3.id, s1.id]
        assert [r.text for r in results] == ["three", "one"]

    def test_missing_ids_are_skipped_not_erroring(self, patched_db):
        from src.db.database import Segment

        session = patched_db.create_video_session(title="v", url="http://x")
        s1 = patched_db.save_segment(Segment(id=None, session_id=session.id, start_s=0.0, end_s=1.0, text="one"))

        results = patched_db.get_segments_by_ids([s1.id, 9999])

        assert [r.id for r in results] == [s1.id]

    def test_empty_ids_returns_empty_list(self, patched_db):
        assert patched_db.get_segments_by_ids([]) == []


class TestGetCallSegmentsByIds:
    def test_returns_rows_preserving_caller_order(self, patched_db):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        id1 = patched_db.save_call_segment(CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="one"))
        id2 = patched_db.save_call_segment(CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="two"))

        results = patched_db.get_call_segments_by_ids([id2, id1])

        assert [r.id for r in results] == [id2, id1]
        assert [r.text for r in results] == ["two", "one"]

    def test_missing_ids_are_skipped_not_erroring(self, patched_db):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        id1 = patched_db.save_call_segment(CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="one"))

        results = patched_db.get_call_segments_by_ids([id1, 9999])

        assert [r.id for r in results] == [id1]

    def test_empty_ids_returns_empty_list(self, patched_db):
        assert patched_db.get_call_segments_by_ids([]) == []
