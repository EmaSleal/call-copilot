"""
Unit tests for PR2 — CategoriesStore (Chroma-backed semantic store for
category dedup), mirroring tests/unit/test_tools_store.py 1:1.

TDD RED phase — tests written against interfaces that do not yet exist.

Authoritative design (sdd/categorias-jerarquicas, design obs #823):
  class CategoriesStore:
      EMBED_MODEL = "text-embedding-3-small"
      COLLECTION  = "categories"
      def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str | None = None): ...
      async def upsert_category(self, category_id: int, embedding_text: str) -> bool
      async def delete_category(self, category_id: int) -> bool
      async def search(self, query: str, top_k: int = 3) -> list[tuple[int, float]]

  def embedding_text(name: str, description: str) -> str

chromadb and openai are stubbed as MagicMock modules in tests/conftest.py.
"""

import sys
from unittest.mock import MagicMock, AsyncMock
import pytest


@pytest.fixture
def mock_collection():
    """A mock Chroma collection with `.upsert`, `.delete` and `.query`."""
    collection = MagicMock()
    return collection


@pytest.fixture
def mock_chromadb(monkeypatch, mock_collection):
    """Patch chromadb.PersistentClient. chromadb is imported lazily inside
    CategoriesStore.__init__ (so the app can start without it installed),
    so we patch the cached module object in sys.modules directly — any
    `import chromadb` inside __init__ resolves to this same object."""
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_persistent_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(sys.modules["chromadb"], "PersistentClient", mock_persistent_client_cls)
    return mock_client


@pytest.fixture
def mock_openai_client():
    """AsyncMock standing in for AsyncOpenAI, matching CategoriesStore._embed() usage."""
    client = MagicMock()
    embedding_response = MagicMock()
    embedding_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.embeddings = MagicMock()
    client.embeddings.create = AsyncMock(return_value=embedding_response)
    return client


# ─────────────────────────────────────────────────────────────
# upsert_category
# ─────────────────────────────────────────────────────────────

class TestUpsertCategory:
    @pytest.mark.asyncio
    async def test_upsert_category_upserts_to_collection_keyed_by_str_id(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.categories_store import CategoriesStore

        store = CategoriesStore(openai_client=mock_openai_client)
        result = await store.upsert_category(category_id=42, embedding_text="Diseño UI/UX — Tipografía y color.")

        assert result is True
        mock_collection.upsert.assert_called_once()
        _, kwargs = mock_collection.upsert.call_args
        assert kwargs["ids"] == ["42"]

    @pytest.mark.asyncio
    async def test_upsert_category_with_none_client_skips_and_returns_false(
        self, mock_chromadb, mock_collection
    ):
        from src.rag.categories_store import CategoriesStore

        store = CategoriesStore(openai_client=None)
        result = await store.upsert_category(category_id=1, embedding_text="Diseño UI/UX")

        assert result is False
        mock_collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_category_with_none_client_raises_nothing(
        self, mock_chromadb, mock_collection
    ):
        from src.rag.categories_store import CategoriesStore

        store = CategoriesStore(openai_client=None)
        # Must not raise.
        await store.upsert_category(category_id=1, embedding_text="Diseño UI/UX")


# ─────────────────────────────────────────────────────────────
# delete_category
# ─────────────────────────────────────────────────────────────

class TestDeleteCategory:
    @pytest.mark.asyncio
    async def test_delete_category_calls_collection_delete_keyed_by_str_id(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.categories_store import CategoriesStore

        store = CategoriesStore(openai_client=mock_openai_client)
        result = await store.delete_category(category_id=7)

        assert result is True
        mock_collection.delete.assert_called_once_with(ids=["7"])

    @pytest.mark.asyncio
    async def test_delete_category_without_collection_returns_false_and_does_not_raise(
        self, monkeypatch, mock_openai_client
    ):
        from src.rag.categories_store import CategoriesStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = CategoriesStore(openai_client=mock_openai_client)

        result = await store.delete_category(category_id=7)

        assert result is False


# ─────────────────────────────────────────────────────────────
# search
# ─────────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_without_openai_client_returns_empty_list(
        self, mock_chromadb, mock_collection
    ):
        from src.rag.categories_store import CategoriesStore

        mock_collection.count.return_value = 5
        store = CategoriesStore(openai_client=None)

        results = await store.search("tipografía y color")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_category_ids_ranked_from_chroma_result(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.categories_store import CategoriesStore

        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "ids": [["42", "7"]],
            "distances": [[0.1, 0.5]],
        }

        store = CategoriesStore(openai_client=mock_openai_client)
        results = await store.search("tipografía y color", top_k=3)

        assert results == [(42, 0.1), (7, 0.5)]

    @pytest.mark.asyncio
    async def test_search_empty_collection_returns_empty_list(
        self, mock_chromadb, mock_collection, mock_openai_client
    ):
        from src.rag.categories_store import CategoriesStore

        mock_collection.count.return_value = 0

        store = CategoriesStore(openai_client=mock_openai_client)
        results = await store.search("tipografía y color")

        assert results == []


# ─────────────────────────────────────────────────────────────
# chromadb genuinely not installed — lazy import degrades gracefully
# ─────────────────────────────────────────────────────────────

class TestCategoriesStoreWithoutChromadb:
    def test_construction_does_not_raise_without_chromadb(self, monkeypatch):
        from src.rag.categories_store import CategoriesStore

        monkeypatch.setitem(sys.modules, "chromadb", None)  # forces ImportError
        CategoriesStore(openai_client=None)  # must not raise

    @pytest.mark.asyncio
    async def test_upsert_category_without_chromadb_returns_false(self, monkeypatch, mock_openai_client):
        from src.rag.categories_store import CategoriesStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = CategoriesStore(openai_client=mock_openai_client)

        result = await store.upsert_category(category_id=1, embedding_text="Diseño UI/UX")

        assert result is False

    @pytest.mark.asyncio
    async def test_search_without_chromadb_returns_empty_list(self, monkeypatch, mock_openai_client):
        from src.rag.categories_store import CategoriesStore

        monkeypatch.setitem(sys.modules, "chromadb", None)
        store = CategoriesStore(openai_client=mock_openai_client)

        results = await store.search("tipografía y color")

        assert results == []


# ─────────────────────────────────────────────────────────────
# embedding_text()
# ─────────────────────────────────────────────────────────────

class TestEmbeddingText:
    def test_joins_name_and_description_with_em_dash(self):
        from src.rag.categories_store import embedding_text

        assert embedding_text("Diseño UI/UX", "Tipografía y color") == "Diseño UI/UX — Tipografía y color"

    def test_strips_surrounding_whitespace(self):
        from src.rag.categories_store import embedding_text

        assert embedding_text("  Diseño UI/UX  ", "  Tipografía y color  ") == "Diseño UI/UX — Tipografía y color"

    def test_empty_description_has_no_dangling_dash(self):
        from src.rag.categories_store import embedding_text

        assert embedding_text("Diseño UI/UX", "") == "Diseño UI/UX"
