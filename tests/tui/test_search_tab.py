"""
Unit tests for _semantic_result_row — Fix #6 (design's parity-fix finding):
a 3-way source label (video/call/note) for the Search tab's semantic
results row, since search_segments_semantic now resolves note segments
too (Fix #4). Pure function — no side effects, no Textual app needed.
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

    def test_note_source_row(self):
        """Before Fix #6, a note result was mislabeled as 'Call' by the
        binary if/else this replaces."""
        from src.tui.tabs.search import _semantic_result_row

        row = _semantic_result_row({"source": "note", "text": "algo"})

        assert row[0] == "Note"
        assert row[0] != "Call"
        assert row[1] == "—"
