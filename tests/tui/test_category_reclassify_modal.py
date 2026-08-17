"""
Unit tests for the global category-reclassify tool (src/processing/category_reclassify.py)
launched from Historial's "Reclasificar categoría..." modal.

Generalizes session-scoped reclassify_otros (tests/tui/test_video_tab.py) in
two ways: (1) works for ANY category, not just "Otro"/"Otros" — the
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
        from src.processing.category_reclassify import reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        nueva = Category(id=2, name="Prompt Engineering", description="d", color="#000")

        video_seg1 = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)
        video_seg2 = Segment(id=11, session_id=6, start_s=0.0, end_s=1.0, text="b", category_id=1)
        call_seg1 = CallSegment(id=20, call_session_id=7, sort_order=0, text="c", category_id=1)

        with (
            patch("src.processing.category_reclassify.db.get_categories", return_value=[tecnico, nueva]),
            patch("src.processing.category_reclassify.db.get_segments_by_category_global",
                  return_value=[video_seg1, video_seg2]),
            patch("src.processing.category_reclassify.db.get_call_segments_by_category_global",
                  return_value=[call_seg1]),
            patch("src.processing.category_reclassify.db.update_segment_category") as mock_update_video,
            patch("src.processing.category_reclassify.db.update_call_segment_category") as mock_update_call,
            patch("src.processing.category_reclassify.classify_segments_batch",
                  side_effect=[[2, None], [2]]),  # first call: video texts, second: call texts
        ):
            moved = asyncio.run(reclassify_category(category_id=1))

        assert moved == 2  # video_seg1 moved, video_seg2 stayed, call_seg1 moved
        mock_update_video.assert_called_once_with(10, 2)
        mock_update_call.assert_called_once_with(20, 2)

    def test_returns_zero_when_nothing_in_category(self):
        from src.processing.category_reclassify import reclassify_category

        with (
            patch("src.processing.category_reclassify.db.get_categories", return_value=[]),
            patch("src.processing.category_reclassify.db.get_segments_by_category_global", return_value=[]),
            patch("src.processing.category_reclassify.db.get_call_segments_by_category_global", return_value=[]),
        ):
            moved = asyncio.run(reclassify_category(category_id=1))

        assert moved == 0

    def test_only_reclassifies_video_when_no_call_segments_match(self):
        from src.processing.category_reclassify import reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        nueva = Category(id=2, name="Prompt Engineering", description="d", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.processing.category_reclassify.db.get_categories", return_value=[tecnico, nueva]),
            patch("src.processing.category_reclassify.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.processing.category_reclassify.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.processing.category_reclassify.db.update_segment_category") as mock_update_video,
            patch("src.processing.category_reclassify.db.update_call_segment_category") as mock_update_call,
            patch("src.processing.category_reclassify.classify_segments_batch", return_value=[2]),
        ):
            moved = asyncio.run(reclassify_category(category_id=1))

        assert moved == 1
        mock_update_video.assert_called_once_with(10, 2)
        mock_update_call.assert_not_called()

    def test_candidates_include_the_target_category_itself(self):
        """The target category MUST stay a valid option — unlike the
        session-scoped reclassify_otros (where excluding "Otro" is correct:
        nothing should ever legitimately re-choose the junk/fallback
        bucket), this tool works on real, substantive categories too. A
        fragment that's still genuinely e.g. "Técnico" after new
        sub-categories are added must be able to stay "Técnico" — forcing
        every fragment away from it with no "stay" option scatters
        legitimate content into worse-fitting categories.

        Regression test: confirmed against real data (91 video + 22 call
        segments) that excluding the target category force-moved 100% of
        them out, most into unrelated categories, when only a fraction
        actually matched the newly suggested sub-categories."""
        from src.processing.category_reclassify import reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.processing.category_reclassify.db.get_categories", return_value=[tecnico]),
            patch("src.processing.category_reclassify.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.processing.category_reclassify.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.processing.category_reclassify.classify_segments_batch") as mock_classify,
        ):
            mock_classify.return_value = [1]  # classifier is allowed to re-pick it
            asyncio.run(reclassify_category(category_id=1))

        candidates_arg = mock_classify.call_args[0][1]
        assert tecnico in candidates_arg

    def test_reclassifying_into_the_same_target_category_does_not_count_as_moved(self):
        """The classifier legitimately re-picking the target category (the
        fragment still belongs there) must not write a no-op update or
        count toward `moved` — nothing actually moved."""
        from src.processing.category_reclassify import reclassify_category

        tecnico = Category(id=1, name="Técnico", description="", color="#000")
        video_seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.processing.category_reclassify.db.get_categories", return_value=[tecnico]),
            patch("src.processing.category_reclassify.db.get_segments_by_category_global", return_value=[video_seg]),
            patch("src.processing.category_reclassify.db.get_call_segments_by_category_global", return_value=[]),
            patch("src.processing.category_reclassify.db.update_segment_category") as mock_update,
            patch("src.processing.category_reclassify.classify_segments_batch", return_value=[1]),
        ):
            moved = asyncio.run(reclassify_category(category_id=1))

        assert moved == 0
        mock_update.assert_not_called()


class TestVerdictLabel:
    """Same duplicate-label rendering used by both VideoTab's and this
    modal's suggestion flow (spec: Duplicate shown with override) — one
    shared implementation in src/processing/category_dedup.py, no longer
    duplicated per-TUI-module."""

    def test_new_suggestion_label_is_plain_name_and_description(self):
        from src.processing.category_dedup import DedupVerdict, verdict_label

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "Campañas"},
            match=None, distance=None, backend="none",
        )

        assert verdict_label(verdict) == "Marketing — Campañas"

    def test_duplicate_label_shows_the_matched_category(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict, verdict_label

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=None, backend="llm-judge",
        )

        assert verdict_label(verdict) == "≈ Jerarquías — Ya existe: Jerarquía visual"

    def test_embeddings_duplicate_label_includes_distance(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict, verdict_label

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=0.123, backend="embeddings",
        )

        assert verdict_label(verdict) == "≈ Jerarquías — Ya existe: Jerarquía visual (d=0.12)"


class TestCreateCheckedSuggestions:
    """`create_checked_suggestions` creates every checked verdict regardless
    of its match (spec: User overrides), skipping only an actual UNIQUE-name
    collision at write time (spec: Fail-open / never silently dropped)."""

    def test_new_suggestion_is_added(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict, create_checked_suggestions

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "d"},
            match=None, distance=None, backend="none",
        )
        created = Category(id=1, name="Marketing", description="d", color="#6366f1")

        with (
            patch(
                "src.processing.category_dedup.db.create_category",
                return_value=created,
            ) as mock_create,
            patch(
                "src.processing.category_dedup.sync_category_embedding"
            ) as mock_sync,
        ):
            added, forced, skipped = asyncio.run(
                create_checked_suggestions([0], [verdict])
            )

        assert added == ["Marketing"]
        assert forced == []
        assert skipped == []
        mock_create.assert_called_once_with("Marketing", "d")
        mock_sync.assert_called_once_with(created)

    def test_checked_duplicate_is_force_created(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict, create_checked_suggestions

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=0.1, backend="embeddings",
        )
        created = Category(id=2, name="Jerarquías", description="d", color="#6366f1")

        with (
            patch(
                "src.processing.category_dedup.db.create_category",
                return_value=created,
            ),
            patch("src.processing.category_dedup.sync_category_embedding"),
        ):
            added, forced, skipped = asyncio.run(
                create_checked_suggestions([0], [verdict])
            )

        assert added == []
        assert forced == ["Jerarquías"]
        assert skipped == []

    def test_integrity_error_is_skipped_not_raised(self):
        import sqlite3

        from src.processing.category_dedup import DedupVerdict, create_checked_suggestions

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "d"},
            match=None, distance=None, backend="none",
        )

        with (
            patch(
                "src.processing.category_dedup.db.create_category",
                side_effect=sqlite3.IntegrityError("UNIQUE constraint failed"),
            ),
            patch(
                "src.processing.category_dedup.sync_category_embedding"
            ) as mock_sync,
        ):
            added, forced, skipped = asyncio.run(
                create_checked_suggestions([0], [verdict])
            )

        assert added == []
        assert forced == []
        assert skipped == ["Marketing"]
        mock_sync.assert_not_called()
