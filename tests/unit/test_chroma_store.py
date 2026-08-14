"""
Unit tests for RAGStore (src/rag/chroma_store.py) — no prior test file
existed for this module. Covers the lazy chromadb import: the app must be
able to start (and a call must be able to run without live RAG) when
chromadb is not installed, instead of crashing at import time.

chromadb and openai are stubbed as MagicMock modules in tests/conftest.py.
"""

import sys
from unittest.mock import MagicMock, AsyncMock
import pytest


@pytest.fixture
def mock_collection():
    collection = MagicMock()
    return collection


@pytest.fixture
def mock_chromadb(monkeypatch, mock_collection):
    """chromadb is imported lazily inside RAGStore.__init__, so we patch the
    cached module object in sys.modules directly."""
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


class TestRAGStoreBasics:
    def test_collection_name_is_set_from_session_id(self, mock_chromadb, mock_openai_client):
        from src.rag.chroma_store import RAGStore

        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)

        assert store.collection_name == "call_abc123"

    @pytest.mark.asyncio
    async def test_add_segment_adds_to_collection(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.chroma_store import RAGStore

        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)
        await store.add_segment("hablamos de Deepgram")

        mock_collection.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_returns_documents_from_chroma_result(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.chroma_store import RAGStore

        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {"documents": [["hablamos de Deepgram"]]}

        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)
        results = await store.search("qué proveedor STT usamos")

        assert results == ["hablamos de Deepgram"]


class TestRAGStoreWithoutChromadb:
    """chromadb was a hard unconditional import before — without it, merely
    starting the app (CallCopilotTab -> session_processor -> tool_extractor
    -> ToolsCatalogStore, or pipeline.py -> RAGStore) would crash."""

    def test_construction_does_not_raise_without_chromadb(self, monkeypatch, mock_openai_client):
        from src.rag.chroma_store import RAGStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        RAGStore(session_id="abc123", openai_client=mock_openai_client)  # must not raise

    def test_collection_name_still_set_without_chromadb(self, monkeypatch, mock_openai_client):
        from src.rag.chroma_store import RAGStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)

        # pipeline.py reads this to persist chroma_collection on the call
        # session row even when RAG itself is disabled.
        assert store.collection_name == "call_abc123"

    @pytest.mark.asyncio
    async def test_add_segment_without_chromadb_does_not_raise(self, monkeypatch, mock_openai_client):
        from src.rag.chroma_store import RAGStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)

        await store.add_segment("hablamos de Deepgram")  # must not raise

    @pytest.mark.asyncio
    async def test_search_without_chromadb_returns_empty_list(self, monkeypatch, mock_openai_client):
        from src.rag.chroma_store import RAGStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = RAGStore(session_id="abc123", openai_client=mock_openai_client)

        results = await store.search("qué proveedor STT usamos")

        assert results == []
