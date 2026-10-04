"""
Unit tests for _semantic_result_row — a 2-way source label (video/call) for
the Search tab's semantic results row. Pure function — no side effects, no
Textual app needed.
"""


class TestSemanticResultRow:
    def test_video_source_row(self):
        from src.tui.tabs.search import _semantic_result_row

        row = _semantic_result_row({"source": "video", "text": "algo", "start_s": 65.0})

        assert row[0] == "Video"
        assert row[1] == "01:05"

    def test_call_source_row(self):
        from src.tui.tabs.search import _semantic_result_row

        row = _semantic_result_row({"source": "call", "text": "algo"})

        assert row[0] == "Call"
        assert row[1] == "—"
