import logging

from openai import AsyncOpenAI

logger = logging.getLogger("call_copilot.rag.tools_store")


class ToolsCatalogStore:
    """Chroma-backed semantic store for the Tools Catalog, keyed by SQLite tool id.

    chromadb is imported lazily so the app can start (and post-call
    extraction/persistence can run) even when it isn't installed — matches
    the other soft-dependency guards in this codebase (OpenAI-optional
    embedding)."""

    EMBED_MODEL = "text-embedding-3-small"
    COLLECTION = "tools_catalog"

    def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str = "data/chroma"):
        self._openai = openai_client
        self._collection = None
        try:
            import chromadb
        except ImportError:
            logger.warning("chromadb no está instalado — Tools Catalog (búsqueda semántica) deshabilitado.")
            return
        client = chromadb.PersistentClient(path=persist_dir)
        self._collection = client.get_or_create_collection(
            name=self.COLLECTION,
            metadata={"hnsw:space": "cosine"},
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

    async def _embed(self, text: str) -> list[float]:
        response = await self._openai.embeddings.create(
            input=text,
            model=self.EMBED_MODEL,
        )
        return response.data[0].embedding
