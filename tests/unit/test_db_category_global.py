"""
Unit tests for global (cross-session) category lookups and the call-side
update_segment_category equivalent — needed by Historial's "reclassify
this category everywhere" tool (mirrors Video's session-scoped
_reclassify_otros, but global and works for any category, not just
"Otro"/"Otros").
"""

import pytest
from pathlib import Path


@pytest.fixture
def patched_db(tmp_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_category_global.db")
    db_module.init_db()
    return db_module


class TestGetSegmentsByCategoryGlobal:
    def test_returns_matches_across_multiple_sessions(self, patched_db):
        from src.db.database import Segment

        cat = patched_db.create_category("Categoría Test", "desc")
        s1 = patched_db.create_video_session(title="v1", url="http://x")
        s2 = patched_db.create_video_session(title="v2", url="http://y")
        seg1 = patched_db.save_segment(
            Segment(id=None, session_id=s1.id, start_s=0.0, end_s=1.0, text="uno", category_id=cat.id)
        )
        seg2 = patched_db.save_segment(
            Segment(id=None, session_id=s2.id, start_s=0.0, end_s=1.0, text="dos", category_id=cat.id)
        )
        patched_db.save_segment(
            Segment(id=None, session_id=s1.id, start_s=1.0, end_s=2.0, text="otro", category_id=None)
        )

        results = patched_db.get_segments_by_category_global(cat.id)

        assert {r.id for r in results} == {seg1.id, seg2.id}

    def test_no_matches_returns_empty_list(self, patched_db):
        cat = patched_db.create_category("Categoría Test", "desc")
        assert patched_db.get_segments_by_category_global(cat.id) == []


class TestGetCallSegmentsByCategoryGlobal:
    def test_returns_matches_across_multiple_call_sessions(self, patched_db):
        from src.db.database import CallSegment

        cat = patched_db.create_category("Categoría Test", "desc")
        cs1 = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/a.txt")
        cs2 = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/b.txt")
        id1 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs1.id, sort_order=0, text="uno", category_id=cat.id)
        )
        id2 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs2.id, sort_order=0, text="dos", category_id=cat.id)
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs1.id, sort_order=1, text="otro", category_id=None)
        )

        results = patched_db.get_call_segments_by_category_global(cat.id)

        assert {r.id for r in results} == {id1, id2}

    def test_no_matches_returns_empty_list(self, patched_db):
        cat = patched_db.create_category("Categoría Test", "desc")
        assert patched_db.get_call_segments_by_category_global(cat.id) == []


class TestUpdateCallSegmentCategory:
    def test_updates_category_id(self, patched_db):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea")
        )
        new_cat = patched_db.create_category("New Cat", "desc")

        patched_db.update_call_segment_category(seg_id, new_cat.id)

        results = {s.id: s for s in patched_db.get_call_segments(cs.id)}
        assert results[seg_id].category_id == new_cat.id

    def test_only_updates_targeted_segment(self, patched_db):
        from src.db.database import CallSegment

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        id1 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="one")
        )
        id2 = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="two")
        )
        new_cat = patched_db.create_category("New Cat", "desc")

        patched_db.update_call_segment_category(id1, new_cat.id)

        results = {s.id: s for s in patched_db.get_call_segments(cs.id)}
        assert results[id1].category_id == new_cat.id
        assert results[id2].category_id is None
