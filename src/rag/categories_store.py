import logging

from openai import AsyncOpenAI

from src.rag.base import ChromaEmbeddingStore

logger = logging.getLogger("call_copilot.rag.categories_store")


class CategoriesStore(ChromaEmbeddingStore):
    """Chroma-backed semantic store for category dedup, keyed by SQLite category id."""

    COLLECTION = "categories"

    def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str | None = None):
        super().__init__(
            openai_client,
            collection_name=self.COLLECTION,
            logger=logger,
            disabled_log_msg="chromadb no está instalado — dedup de categorías (búsqueda semántica) deshabilitado.",
            persist_dir=persist_dir,
        )

    async def upsert_category(self, category_id: int, embedding_text: str) -> bool:
        """Upsert a category's embedding, keyed by str(category_id). Returns False
        (no-op) without an OpenAI client or chromadb — never raises."""
        if not self._openai or self._collection is None:
            return False
        embedding = await self._embed(embedding_text)
        self._collection.upsert(
            ids=[str(category_id)],
            embeddings=[embedding],
            documents=[embedding_text],
        )
        return True

    async def delete_category(self, category_id: int) -> bool:
        """Remove a category's embedding, keyed by str(category_id). Returns False
        (no-op) without chromadb — never raises."""
        if self._collection is None:
            return False
        self._collection.delete(ids=[str(category_id)])
        return True

    async def search(self, query: str, top_k: int = 3) -> list[tuple[int, float]]:
        if not query.strip() or not self._openai or self._collection is None:
            return []
        count = self._collection.count()
        if count == 0:
            return []
        embedding = await self._embed(query)
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
        )
        ids = results["ids"][0] if results["ids"] else []
        distances = results["distances"][0] if results["distances"] else []
        return [(int(category_id), distance) for category_id, distance in zip(ids, distances)]


def embedding_text(name: str, description: str) -> str:
    return f"{name.strip()} — {description.strip()}".strip(" —")
