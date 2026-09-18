"""
Unit tests — PR 1a: Storage foundation for MCP note ingestion.

TDD RED phase — tests written against `src.db.note_segments`, which does
not exist yet.

Covers:
  1.3 save/get/get_by_ids/update_category/delete/next_sort_order
"""

from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_note_segments.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    """Initialize DB against a temp file so every test is isolated."""
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


@pytest.fixture
def note(patched_db):
    from src.db.note_sessions import create_note_session
    return create_note_session(title="A Note")


# ─────────────────────────────────────────────────────────────
# save_note_segment / get_note_segments
# ─────────────────────────────────────────────────────────────

class TestSaveAndGetNoteSegments:
    def test_save_note_segment_returns_id(self, patched_db, note):
        from src.db.note_segments import NoteSegment, save_note_segment
        seg = NoteSegment(id=None, note_id=note.id, sort_order=0, text="First fact")
        returned_id = save_note_segment(seg)
        assert isinstance(returned_id, int)
        assert returned_id > 0

    def test_get_note_segments_returns_matching_rows_ordered(self, patched_db, note):
        from src.db.note_segments import NoteSegment, save_note_segment, get_note_segments
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=1, text="Second"))
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="First"))

        results = get_note_segments(note.id)

        assert [r.text for r in results] == ["First", "Second"]

    def test_get_note_segments_empty_when_none(self, patched_db, note):
        from src.db.note_segments import get_note_segments
        assert get_note_segments(note.id) == []


# ─────────────────────────────────────────────────────────────
# get_note_segments_by_ids
# ─────────────────────────────────────────────────────────────

class TestGetNoteSegmentsByIds:
    def test_returns_rows_preserving_caller_order(self, patched_db, note):
        from src.db.note_segments import NoteSegment, save_note_segment, get_note_segments_by_ids
        id_a = save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="A"))
        id_b = save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=1, text="B"))

        results = get_note_segments_by_ids([id_b, id_a])

        assert [r.id for r in results] == [id_b, id_a]

    def test_empty_ids_returns_empty_list(self, patched_db):
        from src.db.note_segments import get_note_segments_by_ids
        assert get_note_segments_by_ids([]) == []


# ─────────────────────────────────────────────────────────────
# update_note_segment_category
# ─────────────────────────────────────────────────────────────

class TestUpdateNoteSegmentCategory:
    def test_updates_only_targeted_segment(self, patched_db, note):
        from src.db.note_segments import (
            NoteSegment,
            save_note_segment,
            update_note_segment_category,
            get_note_segments,
        )
        target_id = save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="Target"))
        other_id = save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=1, text="Other"))
        cat_id = patched_db.get_categories()[0].id

        update_note_segment_category(target_id, cat_id)

        results = {r.id: r.category_id for r in get_note_segments(note.id)}
        assert results[target_id] == cat_id
        assert results[other_id] is None


# ─────────────────────────────────────────────────────────────
# delete_note_segment
# ─────────────────────────────────────────────────────────────

class TestDeleteNoteSegment:
    def test_soft_deleted_segment_excluded_from_get(self, patched_db, note):
        from src.db.note_segments import NoteSegment, save_note_segment, delete_note_segment, get_note_segments
        seg_id = save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="Gone"))

        delete_note_segment(seg_id)

        assert get_note_segments(note.id) == []


# ─────────────────────────────────────────────────────────────
# next_sort_order
# ─────────────────────────────────────────────────────────────

class TestNextSortOrder:
    def test_zero_when_note_has_no_segments(self, patched_db, note):
        from src.db.note_segments import next_sort_order
        assert next_sort_order(note.id) == 0

    def test_continues_after_existing_max(self, patched_db, note):
        from src.db.note_segments import NoteSegment, save_note_segment, next_sort_order
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="A"))
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=1, text="B"))

        assert next_sort_order(note.id) == 2
