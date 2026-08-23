"""Unit tests for src.video.pipeline._resolve_session — the branch that
lets point 5 (docs/next-steps/feature-proposals.md, MCP-triggered video
processing) hand run_pipeline() an already-claimed session instead of
creating a second one. Isolated the same way test_video_pipeline_indexing.py
isolates _index_saved_segments — run_pipeline() itself stays untested
(whisper/yt-dlp mocking is a much bigger lift than this branch warrants).
"""

from unittest.mock import MagicMock, patch


class TestResolveSession:
    def test_returns_given_session_unchanged_without_creating_or_fetching_title(self):
        from src.db.database import VideoSession
        from src.video import pipeline

        given = VideoSession(id=5, title="Ya reservada", url="https://x", status="processing")
        progress = MagicMock()

        with (
            patch.object(pipeline, "_get_title") as mock_get_title,
            patch.object(pipeline, "create_video_session") as mock_create,
        ):
            result = pipeline._resolve_session("https://x", given, progress)

        assert result is given
        mock_get_title.assert_not_called()
        mock_create.assert_not_called()
        progress.assert_not_called()

    def test_creates_a_new_pending_session_when_none_given(self):
        from src.db.database import VideoSession
        from src.video import pipeline

        created = VideoSession(id=9, title="Título real", url="https://x", status="pending")
        progress = MagicMock()

        with (
            patch.object(pipeline, "_get_title", return_value="Título real") as mock_get_title,
            patch.object(pipeline, "create_video_session", return_value=created) as mock_create,
        ):
            result = pipeline._resolve_session("https://x", None, progress)

        assert result is created
        mock_get_title.assert_called_once_with("https://x")
        mock_create.assert_called_once_with(title="Título real", url="https://x")
        progress.assert_called_once()
