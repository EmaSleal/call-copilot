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
        from src.tui.app import _find_otro_category
        cats = [
            Category(id=1, name="Técnico", description="", color="#000"),
            Category(id=2, name="Otro", description="", color="#000"),
        ]
        assert _find_otro_category(cats).id == 2

    def test_finds_otros_plural(self):
        from src.tui.app import _find_otro_category
        cats = [Category(id=3, name="OTROS", description="", color="#000")]
        assert _find_otro_category(cats).id == 3

    def test_returns_none_when_absent(self):
        from src.tui.app import _find_otro_category
        cats = [Category(id=1, name="Técnico", description="", color="#000")]
        assert _find_otro_category(cats) is None

    def test_returns_none_for_empty_list(self):
        from src.tui.app import _find_otro_category
        assert _find_otro_category([]) is None


class TestPartitionNewSuggestions:
    def test_all_new_when_no_overlap(self):
        from src.tui.app import _partition_new_suggestions
        suggestions = [{"name": "A", "description": "d1"}, {"name": "B", "description": "d2"}]
        new_ones, duplicates = _partition_new_suggestions(suggestions, existing_names=set())
        assert new_ones == suggestions
        assert duplicates == []

    def test_all_duplicate_when_names_exist(self):
        from src.tui.app import _partition_new_suggestions
        suggestions = [{"name": "A", "description": "d1"}]
        new_ones, duplicates = _partition_new_suggestions(suggestions, existing_names={"A"})
        assert new_ones == []
        assert duplicates == suggestions

    def test_mixed_partition(self):
        from src.tui.app import _partition_new_suggestions
        a = {"name": "A", "description": "d1"}
        b = {"name": "B", "description": "d2"}
        new_ones, duplicates = _partition_new_suggestions([a, b], existing_names={"B"})
        assert new_ones == [a]
        assert duplicates == [b]

    def test_empty_suggestions_returns_empty(self):
        from src.tui.app import _partition_new_suggestions
        new_ones, duplicates = _partition_new_suggestions([], existing_names={"A"})
        assert new_ones == []
        assert duplicates == []


class TestReclassifyOtros:
    """
    _reclassify_otros re-checks 'Otro' segments of a session against the
    current category set — the fix for "adding a suggestion doesn't move any
    existing 'Otro' segments into it".
    """

    def test_moves_matching_segments_and_returns_count(self):
        from src.tui.app import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        nueva = Category(id=2, name="Curación Proveedores", description="d", color="#000")
        seg1 = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)
        seg2 = Segment(id=11, session_id=5, start_s=1.0, end_s=2.0, text="b", category_id=1)

        with (
            patch("src.tui.app.db.get_categories", return_value=[otro, nueva]),
            patch("src.tui.app.db.get_segments_by_category", return_value=[seg1, seg2]),
            patch("src.tui.app.db.update_segment_category") as mock_update,
            patch("src.video.classifier.classify_segments_batch", return_value=[2, None]),
        ):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 1
        mock_update.assert_called_once_with(10, 2)

    def test_returns_zero_when_no_otro_category(self):
        from src.tui.app import _reclassify_otros

        with patch("src.tui.app.db.get_categories", return_value=[]):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 0

    def test_returns_zero_when_no_otro_segments(self):
        from src.tui.app import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        with (
            patch("src.tui.app.db.get_categories", return_value=[otro]),
            patch("src.tui.app.db.get_segments_by_category", return_value=[]),
        ):
            moved = asyncio.run(_reclassify_otros(session_id=5))

        assert moved == 0

    def test_excludes_otro_itself_from_candidates(self):
        """The 'Otro' category must not be offered back as a candidate, or the
        LLM could just re-select it and defeat the purpose of reclassifying."""
        from src.tui.app import _reclassify_otros

        otro = Category(id=1, name="Otro", description="", color="#000")
        nueva = Category(id=2, name="Nueva", description="d", color="#000")
        seg = Segment(id=10, session_id=5, start_s=0.0, end_s=1.0, text="a", category_id=1)

        with (
            patch("src.tui.app.db.get_categories", return_value=[otro, nueva]),
            patch("src.tui.app.db.get_segments_by_category", return_value=[seg]),
            patch("src.tui.app.db.update_segment_category"),
            patch("src.video.classifier.classify_segments_batch") as mock_classify,
        ):
            mock_classify.return_value = [None]
            asyncio.run(_reclassify_otros(session_id=5))

        called_categories = mock_classify.call_args[0][1]
        assert otro not in called_categories
