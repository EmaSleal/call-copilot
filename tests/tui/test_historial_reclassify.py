"""
Unit tests for Historial's global category-reclassify tool.

Generalizes Video's session-scoped _reclassify_otros (tests/tui/test_video_tab.py)
in two ways: (1) works for ANY category, not just "Otro"/"Otros" — the
category_id is a parameter, not hardcoded; (2) global across every video
AND call session, not scoped to one session — because a category like
"Técnico" can span dozens of sessions, and breaking it down needs the LLM
to see the whole pattern at once, not one session's slice of it.
"""

import asyncio
from unittest.mock import patch

from src.db.database import CallSegment, Category, Segment


class TestReclassifyCategory:
    def test_moves_matching_video_and_call_segments_and_returns_total_count(self):
        from src.tui.tabs.historial import _reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        nueva = Category(id=2, name="Prompt Engineering", description="d", color="#000")

        video_seg1 = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)
        video_seg2 = Segment(id=11, session_id=6, start_s=0.0, end_s=1.0, text="b", category_id=1)
        call_seg1 = CallSegment(id=20, call_session_id=7, sort_order=0, text="c", category_id=1)

        with (
            patch("src.tui.tabs.historial.db.get_categories", return_value=[tecnico, nueva]),
            patch("src.tui.tabs.historial.db.get_segments_by_category_global",
                  return_value=[video_seg1, video_seg2]),
            patch("src.tui.tabs.historial.db.get_call_segments_by_category_global",
                  return_value=[call_seg1]),
            patch("src.tui.tabs.historial.db.update_segment_category") as mock_update_video,
            patch("src.tui.tabs.historial.db.update_call_segment_category") as mock_update_call,
            patch("src.video.classifier.classify_segments_batch",
                  side_effect=[[2, None], [2]]),  # first call: video texts, second: call texts
        ):
            moved = asyncio.run(_reclassify_category(category_id=1))

        assert moved == 2  # video_seg1 moved, video_seg2 stayed, call_seg1 moved
        mock_update_video.assert_called_once_with(10, 2)
        mock_update_call.assert_called_once_with(20, 2)

    def test_returns_zero_when_nothing_in_category(self):
        from src.tui.tabs.historial import _reclassify_category

        with (
            patch("src.tui.tabs.historial.db.get_categories", return_value=[]),
            patch("src.tui.tabs.historial.db.get_segments_by_category_global", return_value=[]),
            patch("src.tui.tabs.historial.db.get_call_segments_by_category_global", return_value=[]),
        ):
            moved = asyncio.run(_reclassify_category(category_id=1))

        assert moved == 0

    def test_only_reclassifies_video_when_no_call_segments_match(self):
        from src.tui.tabs.historial import _reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        nueva = Category(id=2, name="Prompt Engineering", description="d", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.tui.tabs.historial.db.get_categories", return_value=[tecnico, nueva]),
            patch("src.tui.tabs.historial.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.tui.tabs.historial.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.tui.tabs.historial.db.update_segment_category") as mock_update_video,
            patch("src.tui.tabs.historial.db.update_call_segment_category") as mock_update_call,
            patch("src.video.classifier.classify_segments_batch", return_value=[2]),
        ):
            moved = asyncio.run(_reclassify_category(category_id=1))

        assert moved == 1
        mock_update_video.assert_called_once_with(10, 2)
        mock_update_call.assert_not_called()

    def test_candidates_include_the_target_category_itself(self):
        """The target category MUST stay a valid option — unlike Video's
        _reclassify_otros (where excluding "Otro" is correct: nothing
        should ever legitimately re-choose the junk/fallback bucket),
        Historial's tool works on real, substantive categories too. A
        fragment that's still genuinely e.g. "Técnico" after new
        sub-categories are added must be able to stay "Técnico" — forcing
        every fragment away from it with no "stay" option scatters
        legitimate content into worse-fitting categories.

        Regression test: confirmed against real data (91 video + 22 call
        segments) that excluding the target category force-moved 100% of
        them out, most into unrelated categories, when only a fraction
        actually matched the newly suggested sub-categories."""
        from src.tui.tabs.historial import _reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.tui.tabs.historial.db.get_categories", return_value=[tecnico]),
            patch("src.tui.tabs.historial.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.tui.tabs.historial.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.video.classifier.classify_segments_batch") as mock_classify,
        ):
            mock_classify.return_value = [1]  # classifier is allowed to re-pick it
            asyncio.run(_reclassify_category(category_id=1))

        candidates_arg = mock_classify.call_args[0][1]
        assert tecnico in candidates_arg

    def test_reclassifying_into_the_same_target_category_does_not_count_as_moved(self):
        """The classifier legitimately re-picking the target category (the
        fragment still belongs there) must not write a no-op update or
        count toward `moved` — nothing actually moved."""
        from src.tui.tabs.historial import _reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.tui.tabs.historial.db.get_categories", return_value=[tecnico]),
            patch("src.tui.tabs.historial.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.tui.tabs.historial.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.tui.tabs.historial.db.update_segment_category") as mock_update,
            patch("src.video.classifier.classify_segments_batch", return_value=[1]),
        ):
            moved = asyncio.run(_reclassify_category(category_id=1))

        assert moved == 0
        mock_update.assert_not_called()
