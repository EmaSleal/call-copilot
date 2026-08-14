"""
Unit tests for src.processing.search_indexer — semantic search indexing
for video segments and call segments (a third Chroma-backed search
surface, alongside the live in-call RAGStore and the Tools Catalog).
Coexists with the existing full-text SQL search (database.search_segments)
— never replaces it.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_search_indexer.db")
    db_module.init_db()
    return db_module


@pytest.fixture
def with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")


@pytest.fixture
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


class TestIndexSegment:
    def test_calls_store_add_segment_via_asyncio_run(self, with_openai_key):
        from src.processing import search_indexer

        mock_store = MagicMock()
        mock_store.add_segment = AsyncMock(return_value=True)
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(search_indexer, "SegmentsSearchStore", mock_store_cls):
            result = search_indexer.index_segment("video", 42, "hablamos de Deepgram")

        assert result is True
        mock_store.add_segment.assert_awaited_once_with("video", 42, "hablamos de Deepgram")

    def test_without_openai_key_still_does_not_raise(self, no_openai_key):
        from src.processing import search_indexer

        mock_store = MagicMock()
        mock_store.add_segment = AsyncMock(return_value=False)
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(search_indexer, "SegmentsSearchStore", mock_store_cls):
            result = search_indexer.index_segment("call", 1, "texto")

        assert result is False


class TestSearchSegmentsSemantic:
    @pytest.mark.asyncio
    async def test_joins_video_and_call_results_back_to_sql_rows(self, patched_db, with_openai_key):
        from src.db.database import CallSegment, Segment
        from src.processing import search_indexer

        video_session = patched_db.create_video_session(title="v", url="http://x")
        video_seg = patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="usamos Deepgram")
        )
        call_session = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt")
        call_seg_id = patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=call_session.id, sort_order=0, text="hablamos de OAuth")
        )

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[
            ("video", video_seg.id, 0.1),
            ("call", call_seg_id, 0.2),
        ])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(search_indexer, "SegmentsSearchStore", mock_store_cls):
            results = await search_indexer.search_segments_semantic("STT")

        assert len(results) == 2
        assert results[0]["source"] == "video"
        assert results[0]["text"] == "usamos Deepgram"
        assert results[1]["source"] == "call"
        assert results[1]["text"] == "hablamos de OAuth"

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_list(self, patched_db, with_openai_key):
        from src.processing import search_indexer

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(search_indexer, "SegmentsSearchStore", mock_store_cls):
            results = await search_indexer.search_segments_semantic("nada")

        assert results == []

    @pytest.mark.asyncio
    async def test_stale_id_no_longer_in_sql_is_skipped(self, patched_db, with_openai_key):
        """A composite id the store returns but that no longer resolves to
        a real row (deleted session, etc.) is dropped, not a crash."""
        from src.processing import search_indexer

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[("video", 9999, 0.1)])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(search_indexer, "SegmentsSearchStore", mock_store_cls):
            results = await search_indexer.search_segments_semantic("algo")

        assert results == []
