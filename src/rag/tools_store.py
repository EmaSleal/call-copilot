import logging

from openai import AsyncOpenAI

from src.rag.base import ChromaEmbeddingStore

logger = logging.getLogger("call_copilot.rag.tools_store")


class ToolsCatalogStore(ChromaEmbeddingStore):
    """Chroma-backed semantic store for the Tools Catalog, keyed by SQLite tool id."""

    COLLECTION = "tools_catalog"

    def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str | None = None):
        super().__init__(
            openai_client,
            collection_name=self.COLLECTION,
            logger=logger,
            disabled_log_msg="chromadb no está instalado — Tools Catalog (búsqueda semántica) deshabilitado.",
            persist_dir=persist_dir,
        )

    async def add_tool(self, tool_id: int, embedding_text: str) -> bool:
        """Upsert a tool's embedding, keyed by str(tool_id). Returns False (no-op) without
        an OpenAI client or chromadb — never raises."""
        if not self._openai or self._collection is None:
            return False
        embedding = await self._embed(embedding_text)
        self._collection.upsert(
            ids=[str(tool_id)],
            embeddings=[embedding],
            documents=[embedding_text],
        )
        return True

    async def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
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
        return [(int(tool_id), distance) for tool_id, distance in zip(ids, distances)]
