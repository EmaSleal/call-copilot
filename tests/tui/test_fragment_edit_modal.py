"""
Unit tests for _update_fragment_category — dispatches a category change to
the right DAO based on source. Only "call" exists today; an unrecognized
source must fail closed (raise) rather than guessing.
"""

import pytest
from unittest.mock import patch


class TestUpdateFragmentCategory:
    def test_call_source_calls_update_call_segment_category(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call:
            _update_fragment_category("call", 17, 3)

        mock_call.assert_called_once_with(17, 3)

    def test_unknown_source_raises_value_error(self):
        from src.tui.screens.fragment_edit_modal import _update_fragment_category

        with patch("src.tui.screens.fragment_edit_modal.db.update_call_segment_category") as mock_call:
            with pytest.raises(ValueError):
                _update_fragment_category("bogus", 1, 1)

        mock_call.assert_not_called()
