"""
Unit tests — PR 2: Unified views include the note source (Phase 3).

TDD RED phase — written against the 3rd `UNION ALL` block in
`unified_segments`/`unified_sessions` (source="note"), which does not exist
yet, and against `delete_category`'s note_segments cascade, which does not
exist yet either.

Covers:
  3.1 note appears in get_unified_sessions()/get_unified_segments(source="note");
      soft-delete excluded; delete_category nulls note_segments.category_id.
"""

from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_note_views.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    """Initialize DB against a temp file so every test is isolated."""
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


# ─────────────────────────────────────────────────────────────
# unified_sessions / unified_segments include the note source
# ─────────────────────────────────────────────────────────────

class TestUnifiedViewsIncludeNotes:
    def test_note_session_appears_in_unified_sessions(self, patched_db):
        note = patched_db.create_note_session(title="GPU Notes")

        sessions = patched_db.get_unified_sessions()

        matches = [s for s in sessions if s.source == "note" and s.id == note.id]
        assert len(matches) == 1
        assert matches[0].title == "GPU Notes"

    def test_note_segments_appear_in_unified_segments_filtered_by_source(self, patched_db):
        from src.db.note_segments import NoteSegment, save_note_segment

        note = patched_db.create_note_session(title="GPU Notes")
        seg_id = save_note_segment(
            NoteSegment(id=None, note_id=note.id, sort_order=0, text="CUDA cores")
        )

        segments = patched_db.get_unified_segments(source="note")

        matches = [s for s in segments if s.id == seg_id]
        assert len(matches) == 1
        assert matches[0].source == "note"
        assert matches[0].session_id == note.id
        assert matches[0].text == "CUDA cores"
        assert matches[0].position == 0.0

    def test_note_segments_appear_in_unified_segments_by_session_id(self, patched_db):
        from src.db.note_segments import NoteSegment, save_note_segment

        note = patched_db.create_note_session(title="GPU Notes")
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="A"))

        segments = patched_db.get_unified_segments(source="note", session_id=note.id)

        assert len(segments) == 1
        assert segments[0].text == "A"

    def test_mixed_video_call_note_all_present(self, patched_db):
        from src.db.database import Segment, CallSegment
        from src.db.note_segments import NoteSegment, save_note_segment

        video_session = patched_db.create_video_session(title="Vid", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="video text")
        )
        call_session = patched_db.create_call_session(context="ctx", transcript_path="p.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="call text")
        )
        note = patched_db.create_note_session(title="Note")
        save_note_segment(NoteSegment(id=None, note_id=note.id, sort_order=0, text="note text"))

        segments = patched_db.get_unified_segments()
        sources = {s.source for s in segments}
        assert sources == {"video", "call", "note"}


class TestUnifiedViewsExcludeSoftDeletedNotes:
    def test_soft_deleted_note_session_excluded_from_unified_sessions(self, patched_db):
        note = patched_db.create_note_session(title="Gone Note")
        patched_db.delete_note_session(note.id)

        sessions = patched_db.get_unified_sessions()

        assert all(not (s.source == "note" and s.id == note.id) for s in sessions)

    def test_soft_deleted_note_segment_excluded_from_unified_segments(self, patched_db):
        from src.db.note_segments import NoteSegment, save_note_segment, delete_note_segment

        note = patched_db.create_note_session(title="Note")
        seg_id = save_note_segment(
            NoteSegment(id=None, note_id=note.id, sort_order=0, text="Gone segment")
        )
        delete_note_segment(seg_id)

        segments = patched_db.get_unified_segments(source="note")

        assert all(s.id != seg_id for s in segments)


# ─────────────────────────────────────────────────────────────
# delete_category cascades to note_segments
# ─────────────────────────────────────────────────────────────

class TestDeleteCategoryCascadesToNoteSegments:
    def test_note_segment_category_nulled_on_category_delete(self, patched_db):
        from src.db.note_segments import NoteSegment, save_note_segment, get_note_segments

        cat = patched_db.create_category("Tech", "desc")
        note = patched_db.create_note_session(title="Note")
        seg_id = save_note_segment(
            NoteSegment(id=None, note_id=note.id, sort_order=0, text="text", category_id=cat.id)
        )

        patched_db.delete_category(cat.id)

        results = {r.id: r.category_id for r in get_note_segments(note.id)}
        assert results[seg_id] is None

    def test_existing_cascades_to_segments_and_call_segments_unchanged(self, patched_db):
        from src.db.database import Segment, CallSegment

        cat = patched_db.create_category("Tech", "desc")
        video_session = patched_db.create_video_session(title="Vid", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0,
                    text="v", category_id=cat.id)
        )
        call_session = patched_db.create_call_session(context="ctx", transcript_path="p.txt")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0,
                        text="c", category_id=cat.id)
        )

        patched_db.delete_category(cat.id)

        video_segs = patched_db.get_segments(video_session.id)
        call_segs = patched_db.get_call_segments(call_session.id)
        assert video_segs[0].category_id is None
        assert call_segs[0].category_id is None
