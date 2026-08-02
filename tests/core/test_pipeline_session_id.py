"""
Tests for PR2 pipeline changes:
  2.10  After pipeline.start(), _session_id is a non-None integer
  2.11  pipeline.transcript_path returns a non-empty string after start()

These tests require pipeline to actually call create_call_session and capture
the returned id — currently the pipeline discards the return value.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.core.pipeline import CallCopilotPipeline


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    """Isolated DB for pipeline tests."""
    import src.db.database as db_module
    db_path = tmp_path / "test_pipeline_sid.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


async def _empty_async_gen():
    """Async generator that yields nothing — lets pipeline coroutines complete."""
    return
    yield  # noqa — makes this an async generator


def _build_pipeline(patched_db) -> CallCopilotPipeline:
    """Construct a pipeline with mocked dependencies."""
    return CallCopilotPipeline(
        audio_source=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        trigger=MagicMock(),
        llm=MagicMock(),
        output=MagicMock(),
        llm_enabled=False,
        initial_context="test context",
        min_substantial_words=999,
        # openai_client triggers the create_call_session path inside start()
        openai_client=MagicMock(),
        active_profile=None,
    )


def _run_pipeline_start(pipeline: CallCopilotPipeline) -> None:
    """Start the pipeline and let it run until the async generators exhaust."""
    pipeline.audio_source.start = AsyncMock()
    pipeline.audio_source.stop = AsyncMock()
    pipeline.audio_source.stream = MagicMock(return_value=_empty_async_gen())
    pipeline.stt.connect = AsyncMock()
    pipeline.stt.close = AsyncMock()
    pipeline.stt.transcripts = MagicMock(return_value=_empty_async_gen())

    with patch("src.core.pipeline.RAGStore") as MockRAG:
        mock_rag = MagicMock()
        mock_rag.collection_name = "test_collection"
        MockRAG.return_value = mock_rag
        asyncio.run(pipeline.start())


# ─────────────────────────────────────────────────────────────
# Task 2.10 — pipeline._session_id is non-None int after start()
# ─────────────────────────────────────────────────────────────

class TestPipelineSessionIdCapture:
    def test_session_id_attribute_initialized_to_none(self, patched_db):
        """_session_id must be None before start() is called."""
        pipeline = _build_pipeline(patched_db)
        assert pipeline._session_id is None

    def test_session_id_is_integer_after_start(self, patched_db):
        """After start(), _session_id must be a non-None integer from DB."""
        pipeline = _build_pipeline(patched_db)
        _run_pipeline_start(pipeline)

        assert pipeline._session_id is not None
        assert isinstance(pipeline._session_id, int)
        assert pipeline._session_id > 0

    def test_session_id_matches_db_row(self, patched_db):
        """The captured _session_id must correspond to a real row in call_sessions."""
        pipeline = _build_pipeline(patched_db)
        _run_pipeline_start(pipeline)

        sessions = patched_db.get_call_sessions()
        session_ids = {s.id for s in sessions}
        assert pipeline._session_id in session_ids


# ─────────────────────────────────────────────────────────────
# Task 2.11 — pipeline.transcript_path is non-empty after start()
# ─────────────────────────────────────────────────────────────

class TestPipelineTranscriptPath:
    def test_transcript_path_property_accessible_before_start(self, patched_db):
        """pipeline.transcript_path must be accessible before start() (may be empty)."""
        pipeline = _build_pipeline(patched_db)
        # Should not raise AttributeError
        _ = pipeline.transcript_path

    def test_transcript_path_non_empty_after_start(self, patched_db):
        """After start(), pipeline.transcript_path must be a non-empty string."""
        pipeline = _build_pipeline(patched_db)
        _run_pipeline_start(pipeline)

        path = pipeline.transcript_path
        assert isinstance(path, str)
        assert len(path) > 0

    def test_transcript_path_matches_session_logger(self, patched_db):
        """pipeline.transcript_path must be derived from the session logger's session_id."""
        pipeline = _build_pipeline(patched_db)
        _run_pipeline_start(pipeline)

        # The session logger stores the session_id; the transcript path must include it
        session_id = pipeline.session_logger.session_id
        assert session_id in pipeline.transcript_path
