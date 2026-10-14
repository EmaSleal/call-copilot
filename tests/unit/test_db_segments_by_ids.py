"""
Unit tests for get_call_segments_by_ids — bulk lookup by id,
order-preserving (mirrors get_tools_by_ids' shape), needed to join
semantic search results (composite "<source>:<id>" from
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
