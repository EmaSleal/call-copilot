"""
Unit tests for SegmentsSearchStore (src/rag/segments_store.py) — Chroma-
backed semantic search across video segments AND call segments, keyed by
a composite "<source>:<id>" id (segments.id and call_segments.id are
independent sequences that can collide — same convention Historial
already uses for its own composite row keys).

chromadb and openai are stubbed as MagicMock modules in tests/conftest.py.
"""

import sys
from unittest.mock import MagicMock, AsyncMock
import pytest


@pytest.fixture
def mock_collection():
    return MagicMock()


@pytest.fixture
def mock_chromadb(monkeypatch, mock_collection):
    """chromadb is imported lazily inside SegmentsSearchStore.__init__, so
    we patch the cached module object in sys.modules directly."""
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_persistent_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(sys.modules["chromadb"], "PersistentClient", mock_persistent_client_cls)
    return mock_client


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    embedding_response = MagicMock()
    embedding_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.embeddings = MagicMock()
    client.embeddings.create = AsyncMock(return_value=embedding_response)
    return client


class TestAddSegment:
    @pytest.mark.asyncio
    async def test_upserts_with_composite_id(self, mock_chromadb, mock_collection, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        store = SegmentsSearchStore(openai_client=mock_openai_client)
        result = await store.add_segment("video", 42, "hablamos de Deepgram")

        assert result is True
        mock_collection.upsert.assert_called_once()
        _, kwargs = mock_collection.upsert.call_args
        assert kwargs["ids"] == ["video:42"]

    @pytest.mark.asyncio
    async def test_call_source_composite_id(self, mock_chromadb, mock_collection, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        store = SegmentsSearchStore(openai_client=mock_openai_client)
        await store.add_segment("call", 7, "hablamos de OAuth")

        _, kwargs = mock_collection.upsert.call_args
        assert kwargs["ids"] == ["call:7"]

    @pytest.mark.asyncio
    async def test_without_openai_client_returns_false(self, mock_chromadb, mock_collection):
        from src.rag.segments_store import SegmentsSearchStore

        store = SegmentsSearchStore(openai_client=None)
        result = await store.add_segment("video", 1, "texto")

        assert result is False
        mock_collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_text_returns_false(self, mock_chromadb, mock_collection, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        store = SegmentsSearchStore(openai_client=mock_openai_client)
        result = await store.add_segment("video", 1, "   ")

        assert result is False
        mock_collection.upsert.assert_not_called()


class TestSearch:
    @pytest.mark.asyncio
    async def test_parses_source_and_id_from_composite_results(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.segments_store import SegmentsSearchStore

        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "ids": [["video:42", "call:7"]],
            "distances": [[0.1, 0.3]],
        }

        store = SegmentsSearchStore(openai_client=mock_openai_client)
        results = await store.search("proveedor STT")

        assert results == [("video", 42, 0.1), ("call", 7, 0.3)]

    @pytest.mark.asyncio
    async def test_empty_collection_returns_empty_list(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.segments_store import SegmentsSearchStore

        mock_collection.count.return_value = 0
        store = SegmentsSearchStore(openai_client=mock_openai_client)

        assert await store.search("algo") == []

    @pytest.mark.asyncio
    async def test_without_openai_client_returns_empty_list(self, mock_chromadb, mock_collection):
        from src.rag.segments_store import SegmentsSearchStore

        mock_collection.count.return_value = 5
        store = SegmentsSearchStore(openai_client=None)

        assert await store.search("algo") == []


class TestSegmentsSearchStoreWithoutChromadb:
    """chromadb must stay a soft dependency — same pattern already applied
    to RAGStore and ToolsCatalogStore."""

    def test_construction_does_not_raise(self, monkeypatch, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        SegmentsSearchStore(openai_client=mock_openai_client)  # must not raise

    @pytest.mark.asyncio
    async def test_add_segment_without_chromadb_returns_false(self, monkeypatch, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = SegmentsSearchStore(openai_client=mock_openai_client)

        assert await store.add_segment("video", 1, "texto") is False

    @pytest.mark.asyncio
    async def test_search_without_chromadb_returns_empty_list(self, monkeypatch, mock_openai_client):
        from src.rag.segments_store import SegmentsSearchStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = SegmentsSearchStore(openai_client=mock_openai_client)

        assert await store.search("algo") == []
