"""
Unit tests for SearchTab's pure row-formatting helper for semantic
results. Textual cannot boot headlessly (see test_settings_screen.py's
convention), so only the Textual-free formatting logic is unit-tested
directly.
"""

from src.tui.tabs.search import _semantic_result_row


class TestSemanticResultRow:
    def test_video_result_shows_timestamp(self, spanish):
        result = {"source": "video", "start_s": 65.0, "text": "hablamos de Deepgram"}
        origin, tiempo, _cat, text = _semantic_result_row(result)
        assert origin == "Video"
        assert tiempo == "01:05"
        assert text == "hablamos de Deepgram"

    def test_call_result_shows_dash_for_timestamp(self, spanish):
        result = {"source": "call", "text": "hablamos de OAuth"}
        origin, tiempo, _cat, _text = _semantic_result_row(result)
        assert origin == "Llamada"
        assert tiempo == "—"

    def test_call_result_origin_in_english(self, english):
        result = {"source": "call", "text": "we talked about OAuth"}
        origin, _tiempo, _cat, _text = _semantic_result_row(result)
        assert origin == "Call"

    def test_long_text_is_truncated(self):
        result = {"source": "call", "text": "x" * 100}
        _origin, _tiempo, _cat, text = _semantic_result_row(result)
        assert len(text) == 81
        assert text.endswith("…")
