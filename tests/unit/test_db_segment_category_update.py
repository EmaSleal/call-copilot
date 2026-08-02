"""
Unit tests for update_segment_category — used by post-hoc reclassification
of 'Otro' video segments when a new category is added from a suggestion,
without reprocessing the whole video.
"""

import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_segment_category_update.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestUpdateSegmentCategory:
    def test_updates_category_id(self, patched_db):
        from src.db.database import Segment
        video_session = patched_db.create_video_session(title="v", url="http://x")
        seg = patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="idea")
        )
        new_cat = patched_db.create_category("New Cat", "desc")

        patched_db.update_segment_category(seg.id, new_cat.id)

        results = patched_db.get_segments(video_session.id)
        assert results[0].category_id == new_cat.id

    def test_only_updates_targeted_segment(self, patched_db):
        from src.db.database import Segment
        video_session = patched_db.create_video_session(title="v", url="http://x")
        seg1 = patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="one")
        )
        seg2 = patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=1.0, end_s=2.0, text="two")
        )
        new_cat = patched_db.create_category("New Cat", "desc")

        patched_db.update_segment_category(seg1.id, new_cat.id)

        results = {s.id: s for s in patched_db.get_segments(video_session.id)}
        assert results[seg1.id].category_id == new_cat.id
        assert results[seg2.id].category_id is None
