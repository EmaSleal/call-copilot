"""
Unit tests for _update_fragment_category — dispatches a category change to
the right DAO based on source ("video" -> segments, "call" -> call_segments),
since segments.id and call_segments.id are independent sequences (same
composite-key reasoning as Historial's session rows).
"""

from unittest.mock import patch


class TestUpdateFragmentCategory:
    def test_video_source_calls_update_segment_category(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
        ):
            _update_fragment_category("video", 42, 7)

        mock_video.assert_called_once_with(42, 7)
        mock_call.assert_not_called()

    def test_call_source_calls_update_call_segment_category(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with (
            patch("src.tui.screens.fragment_edit_modal.db.update_segment_category") as mock_video,
            patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call,
        ):
            _update_fragment_category("call", 17, 3)

        mock_call.assert_called_once_with(17, 3)
        mock_video.assert_not_called()
