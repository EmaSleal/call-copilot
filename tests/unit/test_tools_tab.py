"""
Unit tests for ToolsTab's pure row-formatting helper.

Textual cannot boot headlessly (see test_settings_screen.py's convention),
so only the Textual-free row-formatting logic is unit-tested directly.
"""

from src.db.database import Tool
from src.tui.tabs.tools import _tool_row


class TestToolRow:
    def test_uses_category_and_summary(self):
        tool = Tool(
            id=1, name="Chroma", normalized_name="chroma",
            category="Vector DB", summary="Embedded vector database.",
        )
        assert _tool_row(tool) == ("Chroma", "Vector DB", "Embedded vector database.")

    def test_missing_category_shows_dash(self):
        tool = Tool(id=1, name="ripgrep", normalized_name="ripgrep", summary="Fast grep.")
        name, category, _ = _tool_row(tool)
        assert category == "—"

    def test_falls_back_to_description_when_summary_missing(self):
        tool = Tool(
            id=1, name="ripgrep", normalized_name="ripgrep",
            description="Recursive regex search tool.",
        )
        assert _tool_row(tool)[2] == "Recursive regex search tool."

    def test_long_summary_is_truncated(self):
        long_summary = "x" * 100
        tool = Tool(id=1, name="Foo", normalized_name="foo", summary=long_summary)
        _, _, summary = _tool_row(tool)
        assert len(summary) == 81  # 80 chars + ellipsis
        assert summary.endswith("…")
