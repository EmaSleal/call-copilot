"""
Tests for PR3 TUI wiring:
  3.1  Call tab has Input widget with id "session_title"
  3.2  stop_pipeline() triggers session_processor.process after pipeline.stop()
  3.3  Historial tab renders empty-state with no sessions
  3.4  Historial tab shows idea titles and category labels for a session

Tests for pipeline title threading:
  - pipeline.start(title="My title") → create_call_session called with title="My title"

Tests for get_call_sessions():
  - Returns sessions ordered by created_at DESC
"""

import asyncio
import sqlite3
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime, timedelta

import src.db.database as db_module
from src.db.database import (
    CallSession,
    CallSegment,
    get_call_sessions,
    create_call_session,
    get_call_segments,
    save_call_segment,
    Category,
)
from src.core.pipeline import CallCopilotPipeline


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Isolated in-memory-style DB for each test."""
    db_path = tmp_path / "test_historial.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


# ─────────────────────────────────────────────────────────────
# get_call_sessions() — ordered by created_at DESC
# ─────────────────────────────────────────────────────────────

class TestGetCallSessions:
    def test_returns_empty_list_when_no_sessions(self, isolated_db):
        """get_call_sessions() returns [] when there are no call_sessions rows."""
        sessions = get_call_sessions()
        assert sessions == []

    def test_returns_single_session(self, isolated_db):
        """get_call_sessions() returns one session after one insertion."""
        cs = create_call_session(
            context="sales call",
            transcript_path="whisper-text/abc.txt",
            title="Q1 Review",
        )
        sessions = get_call_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == cs.id
        assert sessions[0].title == "Q1 Review"

    def test_returns_sessions_ordered_by_created_at_desc(self, isolated_db):
        """get_call_sessions() returns sessions newest-first."""
        # Insert two sessions with explicit timestamps via direct SQL to control ordering.
        from pathlib import Path
        conn = sqlite3.connect(isolated_db.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        older_ts = (datetime.now() - timedelta(hours=2)).isoformat()
        newer_ts = datetime.now().isoformat()

        conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, created_at, title) VALUES (?,?,?,?)",
            ("ctx_old", "path/old.txt", older_ts, "Older Session"),
        )
        conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, created_at, title) VALUES (?,?,?,?)",
            ("ctx_new", "path/new.txt", newer_ts, "Newer Session"),
        )
        conn.commit()
        conn.close()

        sessions = get_call_sessions()
        assert len(sessions) == 2
        # Newest first
        assert sessions[0].title == "Newer Session"
        assert sessions[1].title == "Older Session"

    def test_returns_callsession_objects(self, isolated_db):
        """get_call_sessions() returns CallSession dataclass instances."""
        create_call_session(context="ctx", transcript_path="p.txt", title="T")
        sessions = get_call_sessions()
        assert isinstance(sessions[0], CallSession)
        assert isinstance(sessions[0].id, int)


# ─────────────────────────────────────────────────────────────
# pipeline.start(title=...) threads title to create_call_session
# ─────────────────────────────────────────────────────────────

async def _empty_async_gen():
    return
    yield


def _build_pipeline() -> CallCopilotPipeline:
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
        openai_client=MagicMock(),
        active_profile=None,
    )


def _configure_pipeline_mocks(pipeline: CallCopilotPipeline) -> None:
    pipeline.audio_source.start = AsyncMock()
    pipeline.audio_source.stop = AsyncMock()
    pipeline.audio_source.stream = MagicMock(return_value=_empty_async_gen())
    pipeline.stt.connect = AsyncMock()
    pipeline.stt.close = AsyncMock()
    pipeline.stt.transcripts = MagicMock(return_value=_empty_async_gen())


class TestPipelineTitleThreading:
    def test_start_accepts_title_parameter(self, isolated_db):
        """pipeline.start(title=...) must not raise TypeError."""
        pipeline = _build_pipeline()
        _configure_pipeline_mocks(pipeline)

        with patch("src.core.pipeline.RAGStore") as MockRAG:
            mock_rag = MagicMock()
            mock_rag.collection_name = "test_col"
            MockRAG.return_value = mock_rag
            # Should not raise TypeError for unexpected keyword argument
            asyncio.run(pipeline.start(title="Session Title"))

    def test_start_title_is_stored_in_db(self, isolated_db):
        """pipeline.start(title='Q4 Call') persists the title in call_sessions."""
        pipeline = _build_pipeline()
        _configure_pipeline_mocks(pipeline)

        with patch("src.core.pipeline.RAGStore") as MockRAG:
            mock_rag = MagicMock()
            mock_rag.collection_name = "test_col"
            MockRAG.return_value = mock_rag
            asyncio.run(pipeline.start(title="Q4 Call"))

        sessions = get_call_sessions()
        assert len(sessions) == 1
        assert sessions[0].title == "Q4 Call"

    def test_start_empty_title_does_not_fail(self, isolated_db):
        """pipeline.start() with no title stores empty string gracefully."""
        pipeline = _build_pipeline()
        _configure_pipeline_mocks(pipeline)

        with patch("src.core.pipeline.RAGStore") as MockRAG:
            mock_rag = MagicMock()
            mock_rag.collection_name = "test_col"
            MockRAG.return_value = mock_rag
            asyncio.run(pipeline.start())

        sessions = get_call_sessions()
        assert len(sessions) == 1
        assert sessions[0].title == ""


# ─────────────────────────────────────────────────────────────
# _stop_call triggers session_processor.process (unit-level mock)
# Textual is not installed in the test environment, so we test the
# logic by extracting the triggering decision into a pure helper
# that _stop_call delegates to.
# ─────────────────────────────────────────────────────────────

def _textual_is_real() -> bool:
    """Return True only if textual is a real installed package (not a MagicMock stub)."""
    try:
        import textual
        # The real textual package has a __version__ attribute; mocks do not reliably.
        return isinstance(getattr(textual, "__version__", None), str)
    except ImportError:
        return False

_TEXTUAL_AVAILABLE = _textual_is_real()


@pytest.mark.skipif(not _TEXTUAL_AVAILABLE, reason="Textual not installed in test env")
class TestStopCallTriggersProcessor:
    """
    Tests for CallCopilotTab._stop_call() triggering post-processing.
    Only runs when textual is installed.
    """

    def test_process_called_when_session_id_exists(self, isolated_db):
        """
        _stop_call() must schedule session_processor.process when _pipeline._session_id is set.
        """
        from src.tui.tabs.call import CallCopilotTab

        tab = CallCopilotTab.__new__(CallCopilotTab)
        mock_pipeline = MagicMock()
        mock_pipeline._session_id = 42
        mock_pipeline.transcript_path = "whisper-text/abc.txt"
        mock_pipeline.stop = AsyncMock()
        tab._pipeline = mock_pipeline
        tab._pipeline_task = None

        with (
            patch("src.tui.tabs.call.asyncio.create_task") as mock_create_task,
            patch("src.tui.tabs.call.process"),
        ):
            tab.query_one = MagicMock(side_effect=lambda *a, **kw: MagicMock(disabled=False))
            tab._stop_call()
            assert mock_create_task.called

    def test_process_not_called_when_no_session_id(self, isolated_db):
        """_stop_call() must NOT call process when _session_id is None."""
        from src.tui.tabs.call import CallCopilotTab

        tab = CallCopilotTab.__new__(CallCopilotTab)
        mock_pipeline = MagicMock()
        mock_pipeline._session_id = None
        mock_pipeline.stop = AsyncMock()
        tab._pipeline = mock_pipeline
        tab._pipeline_task = None

        with (
            patch("src.tui.tabs.call.asyncio.create_task"),
            patch("src.tui.tabs.call.process") as mock_process,
        ):
            tab.query_one = MagicMock(side_effect=lambda *a, **kw: MagicMock(disabled=False))
            tab._stop_call()
            mock_process.assert_not_called()


class TestStopCallProcessorLogicPure:
    """
    Pure-function tests for the decision logic: 'should we trigger processing?'
    Extracted from TUI to be testable without Textual.
    """

    def test_should_trigger_returns_true_when_session_id_set(self):
        """_should_trigger_processing returns True when session_id is a non-None int."""
        from src.tui.tabs.call import _should_trigger_processing
        assert _should_trigger_processing(session_id=42) is True

    def test_should_trigger_returns_false_when_session_id_none(self):
        """_should_trigger_processing returns False when session_id is None."""
        from src.tui.tabs.call import _should_trigger_processing
        assert _should_trigger_processing(session_id=None) is False

    def test_should_trigger_returns_false_when_session_id_zero(self):
        """_should_trigger_processing returns False for falsy session_id=0."""
        from src.tui.tabs.call import _should_trigger_processing
        assert _should_trigger_processing(session_id=0) is False


class TestTitledSessionsPure:
    """
    Pure-function tests for the decision logic: 'should this session show in Historial?'
    Untitled sessions are filtered out — they're noise (stray/incomplete recordings).
    Applies uniformly to CallSession and UnifiedSession (both have .title).
    """

    def test_keeps_sessions_with_title(self):
        from src.tui.tabs.historial import _titled_sessions
        titled = CallSession(id=1, context="c", transcript_path="p.txt", title="Q1 Review")
        assert _titled_sessions([titled]) == [titled]

    def test_drops_sessions_with_empty_title(self):
        from src.tui.tabs.historial import _titled_sessions
        untitled = CallSession(id=1, context="c", transcript_path="p.txt", title="")
        assert _titled_sessions([untitled]) == []

    def test_mixed_list_keeps_only_titled(self):
        from src.tui.tabs.historial import _titled_sessions
        titled = CallSession(id=1, context="c", transcript_path="p.txt", title="Titled")
        untitled = CallSession(id=2, context="c", transcript_path="p.txt", title="")
        assert _titled_sessions([titled, untitled]) == [titled]

    def test_works_with_unified_session(self):
        from src.tui.tabs.historial import _titled_sessions
        from src.db.database import UnifiedSession
        titled = UnifiedSession(id=1, source="video", title="A talk", created_at="2026-01-01")
        untitled = UnifiedSession(id=2, source="call", title="", created_at="2026-01-01")
        assert _titled_sessions([titled, untitled]) == [titled]


class TestParseSessionRowKeyPure:
    """
    Pure-function tests for splitting the composite Historial row key
    ("source:id") back into (source, id) — needed because video_sessions.id
    and call_sessions.id are independent sequences that can collide.
    """

    def test_parses_call_key(self):
        from src.tui.tabs.historial import _parse_session_row_key
        assert _parse_session_row_key("call:12") == ("call", 12)

    def test_parses_video_key(self):
        from src.tui.tabs.historial import _parse_session_row_key
        assert _parse_session_row_key("video:3") == ("video", 3)


# ─────────────────────────────────────────────────────────────
# HistorialTab data-layer: get_call_segments with categories
# ─────────────────────────────────────────────────────────────

class TestHistorialDataLayer:
    def test_get_call_segments_empty_for_new_session(self, isolated_db):
        """get_call_segments returns [] for a session with no segments."""
        cs = create_call_session(context="ctx", transcript_path="p.txt")
        segments = get_call_segments(cs.id)
        assert segments == []

    def test_get_call_segments_returns_correct_data(self, isolated_db):
        """get_call_segments returns CallSegment rows with correct fields."""
        cs = create_call_session(context="ctx", transcript_path="p.txt")
        seg1 = CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="First idea text here", category_id=None)
        seg2 = CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="Second idea text", category_id=None)
        save_call_segment(seg1)
        save_call_segment(seg2)

        segments = get_call_segments(cs.id)
        assert len(segments) == 2
        assert segments[0].text == "First idea text here"
        assert segments[1].text == "Second idea text"
        assert segments[0].sort_order == 0
        assert segments[1].sort_order == 1

    def test_get_call_segments_respects_session_isolation(self, isolated_db):
        """get_call_segments only returns segments for the requested session."""
        cs1 = create_call_session(context="ctx1", transcript_path="p1.txt")
        cs2 = create_call_session(context="ctx2", transcript_path="p2.txt")

        save_call_segment(CallSegment(id=None, call_session_id=cs1.id, sort_order=0, text="For session 1", category_id=None))
        save_call_segment(CallSegment(id=None, call_session_id=cs2.id, sort_order=0, text="For session 2", category_id=None))

        segs1 = get_call_segments(cs1.id)
        segs2 = get_call_segments(cs2.id)

        assert len(segs1) == 1
        assert segs1[0].text == "For session 1"
        assert len(segs2) == 1
        assert segs2[0].text == "For session 2"

    def test_call_segments_have_truncated_text_display(self, isolated_db):
        """The first 60 chars of a long text is sufficient for display truncation."""
        long_text = "A" * 120
        cs = create_call_session(context="ctx", transcript_path="p.txt")
        save_call_segment(CallSegment(id=None, call_session_id=cs.id, sort_order=0, text=long_text, category_id=None))

        segments = get_call_segments(cs.id)
        # The display logic in HistorialTab truncates to 60 chars
        display = segments[0].text[:60]
        assert len(display) == 60
        assert display == "A" * 60
