"""
Pure-function tests for VideoTab's "Analizar otros" / suggestion-add flow.

Context: accepting a suggested category used to crash with an unhandled
IntegrityError when the LLM re-suggested a category name that already
existed (categories.name has a UNIQUE constraint). These pure helpers
carry the decision logic so it's testable without Textual or sqlite.
"""

import asyncio
from unittest.mock import patch

from src.db.database import Category, Segment


class TestFindOtroCategory:
    def test_finds_otro_case_insensitive(self):
        from src.tui.tabs.video import _find_otro_category
        cats = [
            Category(id=1, name="Técnico", description="", color="#000"),
            Category(id=2, name="Otro", description="", color="#000"),
        ]
        assert _find_otro_category(cats).id == 2

    def test_finds_otros_plural(self):
        from src.tui.tabs.video import _find_otro_category
        cats = [Category(id=3, name="OTROS", description="", color="#000")]
        assert _find_otro_category(cats).id == 3

    def test_returns_none_when_absent(self):
        from src.tui.tabs.video import _find_otro_category
        cats = [Category(id=1, name="Técnico", description="", color="#000")]
        assert _find_otro_category(cats) is None

    def test_returns_none_for_empty_list(self):
        from src.tui.tabs.video import _find_otro_category
        assert _find_otro_category([]) is None


class TestVerdictLabel:
    """Duplicate-suggestion labelling for the SelectionList (spec: Duplicate
    shown with override)."""

    def test_new_suggestion_label_is_plain_name_and_description(self):
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _verdict_label

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "Campañas"},
            match=None, distance=None, backend="none",
        )

        assert _verdict_label(verdict) == "Marketing — Campañas"

    def test_duplicate_label_shows_the_matched_category(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _verdict_label

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=None, backend="llm-judge",
        )

        assert _verdict_label(verdict) == "≈ Jerarquías — Ya existe: Jerarquía visual"

    def test_embeddings_duplicate_label_includes_distance(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _verdict_label

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=0.123, backend="embeddings",
        )

        assert _verdict_label(verdict) == "≈ Jerarquías — Ya existe: Jerarquía visual (d=0.12)"

    def test_llm_judge_duplicate_label_has_no_distance_suffix(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _verdict_label

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=None, backend="llm-judge",
        )

        assert "(d=" not in _verdict_label(verdict)


class TestCreateCheckedSuggestions:
    """`_create_checked_suggestions` creates every checked verdict regardless
    of its match (spec: User overrides), skipping only an actual UNIQUE-name
    collision at write time (spec: Fail-open / never silently dropped)."""

    def test_new_suggestion_is_added(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _create_checked_suggestions

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "d"},
            match=None, distance=None, backend="none",
        )
        created = Category(id=1, name="Marketing", description="d", color="#6366f1")

        with (
            patch("src.tui.tabs.video.db.create_category", return_value=created) as mock_create,
            patch("src.tui.tabs.video.sync_category_embedding") as mock_sync,
        ):
            added, forced, skipped = asyncio.run(
                _create_checked_suggestions([0], [verdict])
            )

        assert added == ["Marketing"]
        assert forced == []
        assert skipped == []
        mock_create.assert_called_once_with("Marketing", "d")
        mock_sync.assert_called_once_with(created)

    def test_checked_duplicate_is_force_created(self):
        from src.db.database import Category
        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _create_checked_suggestions

        match = Category(id=9, name="Jerarquía visual", description="", color="#000")
        verdict = DedupVerdict(
            suggestion={"name": "Jerarquías", "description": "d"},
            match=match, distance=0.1, backend="embeddings",
        )
        created = Category(id=2, name="Jerarquías", description="d", color="#6366f1")

        with (
            patch("src.tui.tabs.video.db.create_category", return_value=created),
            patch("src.tui.tabs.video.sync_category_embedding"),
        ):
            added, forced, skipped = asyncio.run(
                _create_checked_suggestions([0], [verdict])
            )

        assert added == []
        assert forced == ["Jerarquías"]
        assert skipped == []

    def test_integrity_error_is_skipped_not_raised(self):
        import sqlite3

        from src.processing.category_dedup import DedupVerdict
        from src.tui.tabs.video import _create_checked_suggestions

        verdict = DedupVerdict(
            suggestion={"name": "Marketing", "description": "d"},
            match=None, distance=None, backend="none",
        )

        with (
            patch(
                "src.tui.tabs.video.db.create_category",
                side_effect=sqlite3.IntegrityError("UNIQUE constraint failed"),
            ),
            patch("src.tui.tabs.video.sync_category_embedding") as mock_sync,
        ):
            added, forced, skipped = asyncio.run(
                _create_checked_suggestions([0], [verdict])
            )

        assert added == []
        assert forced == []
        assert skipped == ["Marketing"]
        mock_sync.assert_not_called()

    def test_empty_selection_returns_empty_lists(self):
        from src.tui.tabs.video import _create_checked_suggestions

        added, forced, skipped = asyncio.run(_create_checked_suggestions([], []))

        assert added == []
        assert forced == []
        assert skipped == []


class TestReclassifyOtros:
    """
    _reclassify_otros re-checks 'Otro' segments of a session against the
    current category set — the fix for "adding a suggestion doesn't move any
    existing 'Otro' segments into it".
    """

    def test_moves_matching_segments_and_returns_count(self):
        from src.tui.tabs.video import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        nueva = Category(id=2, name="Curación Proveedores", description="d", color="#000")
        seg1 = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)
        seg2 = Segment(id=11, session_id=5, start_s=1.0, end_s=2.0, text="b", category_id=1)

        with (
            patch("src.tui.tabs.video.db.get_categories", return_value=[otro, nueva]),
            patch("src.tui.tabs.video.db.get_segments_by_category", return_value=[seg1, seg2]),
            patch("src.tui.tabs.video.db.update_segment_category") as mock_update,
            patch("src.video.classifier.classify_segments_batch", return_value=[2, None]),
        ):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 1
        mock_update.assert_called_once_with(10, 2)

    def test_returns_zero_when_no_otro_category(self):
        from src.tui.tabs.video import _reclassify_otros

        with patch("src.tui.tabs.video.db.get_categories", return_value=[]):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 0

    def test_returns_zero_when_no_otro_segments(self):
        from src.tui.tabs.video import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        with (
            patch("src.tui.tabs.video.db.get_categories", return_value=[otro]),
            patch("src.tui.tabs.video.db.get_segments_by_category", return_value=[]),
        ):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 0

    def test_excludes_otro_itself_from_candidates(self):
        """The 'Otro' category must not be offered back as a candidate, or the
        LLM could just re-select it and defeat the purpose of reclassifying."""
        from src.tui.tabs.video import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        nueva = Category(id=2, name="Nueva", description="d", color="#000")
        seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.tui.tabs.video.db.get_categories", return_value=[otro, nueva]),
            patch("src.tui.tabs.video.db.get_segments_by_category", return_value=[seg]),
            patch("src.tui.tabs.video.db.update_segment_category"),
            patch("src.video.classifier.classify_segments_batch") as mock_classify,
        ):
            mock_classify.return_value = [None]
            asyncio.run(_reclassify_otros(session_id=5))

        called_categories = mock_classify.call_args[0][1]
        assert otro not in called_categories
