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


class TestDeleteCategory:
    def test_deleting_category_referenced_by_call_segments_nulls_it_out(self, patched_db):
        """Spec: Delete category referenced by call_segments — under
        PRAGMA foreign_keys=ON, deleting a category still referenced by a
        call_segments row must not raise an FK violation, and that row's
        category_id must become NULL."""
        from src.db.database import CallSegment

        cat = patched_db.create_category("Categoría Test", "desc")
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea", category_id=cat.id)
        )

        patched_db.delete_category(cat.id)

        results = {s.id: s for s in patched_db.get_call_segments(cs.id)}
        assert results[seg_id].category_id is None

    def test_deleting_parent_category_promotes_children_to_top_level(self, patched_db):
        """Spec: Delete parent promotes children — children keep existing,
        never cascade-deleted, with parent_id reset to NULL."""
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)

        patched_db.delete_category(parent.id)

        remaining = {c.id: c for c in patched_db.get_categories()}
        assert child.id in remaining
        assert remaining[child.id].parent_id is None


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
