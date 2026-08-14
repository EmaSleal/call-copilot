import chromadb
from openai import AsyncOpenAI


class ToolsCatalogStore:
    """Chroma-backed semantic store for the Tools Catalog, keyed by SQLite tool id."""

    EMBED_MODEL = "text-embedding-3-small"
    COLLECTION = "tools_catalog"

    def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str = "data/chroma"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._openai = openai_client

    async def add_tool(self, tool_id: int, embedding_text: str) -> bool:
        """Upsert a tool's embedding, keyed by str(tool_id). Returns False (no-op) without
        an OpenAI client — never raises."""
        if not self._openai:
            return False
        embedding = await self._embed(embedding_text)
        self._collection.upsert(
            ids=[str(tool_id)],
            embeddings=[embedding],
            documents=[embedding_text],
        )
        return True

    async def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        if not query.strip():
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
