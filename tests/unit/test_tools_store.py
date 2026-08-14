"""
Unit tests for PR1 — ToolsCatalogStore (Chroma-backed semantic store for the
Tools Catalog).

TDD RED phase — tests written against interfaces that do not yet exist.

Authoritative design (sdd/tools-catalog):
  class ToolsCatalogStore:
      EMBED_MODEL = "text-embedding-3-small"
      COLLECTION  = "tools_catalog"
      def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str = "data/chroma"): ...
      async def add_tool(self, tool_id: int, embedding_text: str) -> bool   # False = skipped
      async def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]
      async def _embed(self, text: str) -> list[float]

chromadb and openai are stubbed as MagicMock modules in tests/conftest.py.
"""

from unittest.mock import MagicMock, AsyncMock
import pytest


@pytest.fixture
def mock_collection():
    """A mock Chroma collection with `.upsert` and `.query`."""
    collection = MagicMock()
    return collection


@pytest.fixture
def mock_chromadb(monkeypatch, mock_collection):
    """Patch chromadb.PersistentClient used inside src.rag.tools_store."""
    import src.rag.tools_store as tools_store_module

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_persistent_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(tools_store_module.chromadb, "PersistentClient", mock_persistent_client_cls)
    return mock_client


@pytest.fixture
def mock_openai_client():
    """AsyncMock standing in for AsyncOpenAI, matching RAGStore's _embed() usage."""
    client = MagicMock()
    embedding_response = MagicMock()
    embedding_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.embeddings = MagicMock()
    client.embeddings.create = AsyncMock(return_value=embedding_response)
    return client


# ─────────────────────────────────────────────────────────────
# Phase 4 — add_tool
# ─────────────────────────────────────────────────────────────

class TestAddTool:
    @pytest.mark.asyncio
    async def test_add_tool_upserts_to_collection_keyed_by_str_id(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.tools_store import ToolsCatalogStore

        store = ToolsCatalogStore(openai_client=mock_openai_client)
        result = await store.add_tool(tool_id=42, embedding_text="Chroma. Vector DB. Used for RAG.")

        assert result is True
        mock_collection.upsert.assert_called_once()
        _, kwargs = mock_collection.upsert.call_args
        assert kwargs["ids"] == ["42"]

    @pytest.mark.asyncio
    async def test_add_tool_with_none_client_skips_and_returns_false(
        self, mock_chromadb, mock_collection
    ):
        from src.rag.tools_store import ToolsCatalogStore

        store = ToolsCatalogStore(openai_client=None)
        result = await store.add_tool(tool_id=1, embedding_text="Deepgram. STT provider.")

        assert result is False
        mock_collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_tool_with_none_client_raises_nothing(
        self, mock_chromadb, mock_collection
    ):
        from src.rag.tools_store import ToolsCatalogStore

        store = ToolsCatalogStore(openai_client=None)
        # Must not raise.
        await store.add_tool(tool_id=1, embedding_text="Deepgram.")


# ─────────────────────────────────────────────────────────────
# Phase 4 — search
# ─────────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_tool_ids_ranked_from_chroma_result(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.tools_store import ToolsCatalogStore

        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "ids": [["42", "7"]],
            "distances": [[0.1, 0.5]],
        }

        store = ToolsCatalogStore(openai_client=mock_openai_client)
        results = await store.search("vector database", top_k=5)

        assert results == [(42, 0.1), (7, 0.5)]

    @pytest.mark.asyncio
    async def test_search_empty_collection_returns_empty_list(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.tools_store import ToolsCatalogStore

        mock_collection.count.return_value = 0

        store = ToolsCatalogStore(openai_client=mock_openai_client)
        results = await store.search("vector database")

        assert results == []
