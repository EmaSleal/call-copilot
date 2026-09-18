"""
Unit tests for _update_fragment_category — dispatches a category change to
the right DAO based on source ("video" -> segments, "call" -> call_segments,
"note" -> note_segments), since segments.id, call_segments.id and
note_segments.id are INDEPENDENT AUTOINCREMENT sequences that can collide
(same composite-key reasoning as Historial's session rows). An unrecognized
source must fail closed (raise) rather than silently writing into
call_segments.
"""

import pytest
from unittest.mock import patch


class TestUpdateFragmentCategory:
    def test_video_source_calls_update_segment_category(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
            patch("src.tui.screens.fragment_edit_modal.db.update_note_segment_category") as mock_note,
        ):
            _update_fragment_category("video", 42, 7)

        mock_video.assert_called_once_with(42, 7)
        mock_call.assert_not_called()
        mock_note.assert_not_called()

    def test_call_source_calls_update_call_segment_category(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
            patch("src.tui.screens.fragment_edit_modal.db.update_note_segment_category") as mock_note,
        ):
            _update_fragment_category("call", 17, 3)

        mock_call.assert_called_once_with(17, 3)
        mock_video.assert_not_called()
        mock_note.assert_not_called()

    def test_note_source_calls_update_note_segment_category(self):
        """Regression for the corruption-risk fix: a note fragment edit must
        route to update_note_segment_category ONLY. Proven meaningful by an
        id-collision fixture below (a note_segment and a call_segment sharing
        the same integer id) — a test that can't fail without the fix isn't
        proving anything."""
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
            patch("src.tui.screens.fragment_edit_modal.db.update_note_segment_category") as mock_note,
        ):
            _update_fragment_category("note", 42, 9)

        mock_note.assert_called_once_with(42, 9)
        mock_call.assert_not_called()
        mock_video.assert_not_called()

    def test_unknown_source_raises_value_error(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
            patch("src.tui.screens.fragment_edit_modal.db.update_note_segment_category") as mock_note,
        ):
            with pytest.raises(ValueError):
                _update_fragment_category("bogus", 1, 1)

        mock_video.assert_not_called()
        mock_call.assert_not_called()
        mock_note.assert_not_called()


class TestNoteFragmentDispatchDoesNotCorruptCallSegments:
    """Real-DB regression: a note_segment and a call_segment sharing the same
    AUTOINCREMENT id must not collide when editing the note's category —
    this is the exact corruption window Fix #1 closes. A pre-fix `else`
    dispatch would route this note edit into update_call_segment_category
    and silently corrupt the unrelated call fragment."""

    def test_note_edit_never_touches_call_segment_with_colliding_id(self, tmp_path, monkeypatch):
        import src.db.database as db_module
        from src.db.database import CallSegment
        from src.db.note_segments import NoteSegment, save_note_segment
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        db_path = tmp_path / "test_fragment_dispatch.db"
        monkeypatch.setattr(db_module, "DB_PATH", db_path)
        db_module.init_db()

        cat_a = db_module.create_category("A", "desc")
        cat_b = db_module.create_category("B", "desc")

        call_session = db_module.create_call_session(context="ctx", transcript_path="p.txt")
        call_seg_id = db_module.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0,
                        text="call fragment", category_id=cat_a.id)
        )

        note = db_module.create_note_session(title="Note")
        note_seg_id = save_note_segment(
            NoteSegment(id=None, note_id=note.id, sort_order=0,
                        text="note fragment", category_id=cat_a.id)
        )

        # Force the collision fixture the design calls for: make the note
        # segment share the same integer id as the call segment (both
        # tables use independent AUTOINCREMENT sequences, so this can
        # legitimately happen in production).
        assert call_seg_id == note_seg_id, (
            "fixture setup expects both DAOs to hand out id=1 for their "
            "first insert into a fresh temp DB — if this fails, adjust the "
            "fixture so the ids actually collide"
        )

        _update_fragment_category("note", note_seg_id, cat_b.id)

        call_segs = db_module.get_call_segments(call_session.id)
        assert call_segs[0].category_id == cat_a.id, (
            "editing the note fragment must NOT have touched the "
            "colliding call_segments row"
        )

        from src.db.note_segments import get_note_segments
        note_segs = get_note_segments(note.id)
        assert note_segs[0].category_id == cat_b.id
