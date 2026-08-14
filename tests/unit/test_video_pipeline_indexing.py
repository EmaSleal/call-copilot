"""
Unit tests for src.video.pipeline._index_saved_segments — the semantic
search indexing hook for video segments. run_pipeline() itself has no
test scaffold (whisper/yt-dlp/classify_segments_batch all need mocking
just to exercise it, a much bigger lift than this hook warrants), so this
targets the extracted, directly-testable indexing step in isolation —
same best-effort/never-blocks-the-report contract as the equivalent hook
already covered in test_session_processor.py.
"""

from unittest.mock import MagicMock, patch


class TestIndexSavedSegments:
    def test_calls_index_segment_once_per_saved_segment(self):
        from src.db.database import Segment
        from src.video import pipeline

        segments = [
            Segment(id=1, session_id=10, start_s=0.0, end_s=1.0, text="uno"),
            Segment(id=2, session_id=10, start_s=1.0, end_s=2.0, text="dos"),
        ]

        with patch.object(pipeline, "index_segment") as mock_index:
            pipeline._index_saved_segments(10, segments)

        assert mock_index.call_count == 2
        mock_index.assert_any_call("video", 1, "uno")
        mock_index.assert_any_call("video", 2, "dos")

    def test_raising_does_not_propagate(self):
        from src.db.database import Segment
        from src.video import pipeline

        segments = [Segment(id=1, session_id=10, start_s=0.0, end_s=1.0, text="uno")]

        with patch.object(pipeline, "index_segment", side_effect=Exception("boom")):
            pipeline._index_saved_segments(10, segments)  # must not raise

    def test_raising_logs_error(self):
        from src.db.database import Segment
        from src.video import pipeline

        segments = [Segment(id=1, session_id=10, start_s=0.0, end_s=1.0, text="uno")]

        with patch.object(pipeline, "index_segment", side_effect=Exception("boom")):
            with patch.object(pipeline, "logger") as mock_logger:
                pipeline._index_saved_segments(10, segments)

        mock_logger.error.assert_called_once()

    def test_empty_segments_is_a_no_op(self):
        from src.video import pipeline

        with patch.object(pipeline, "index_segment") as mock_index:
            pipeline._index_saved_segments(10, [])

        mock_index.assert_not_called()
