import uuid
from datetime import datetime
import chromadb
from openai import AsyncOpenAI


class RAGStore:
    """ChromaDB-backed segment store with OpenAI embeddings."""

    EMBED_MODEL = "text-embedding-3-small"

    def __init__(self, session_id: str, openai_client: AsyncOpenAI, persist_dir: str = "data/chroma"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=f"call_{session_id}",
            metadata={"hnsw:space": "cosine"},
        )
        self._openai = openai_client
        self.session_id = session_id
        self.collection_name = f"call_{session_id}"

    async def add_segment(self, text: str, timestamp: str | None = None) -> None:
        if not text.strip():
            return
        embedding = await self._embed(text)
        self._collection.add(
            ids=[str(uuid.uuid4())],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"timestamp": timestamp or datetime.now().isoformat()}],
        )

    async def search(self, query: str, top_k: int = 5) -> list[str]:
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
        return results["documents"][0] if results["documents"] else []

    async def _embed(self, text: str) -> list[float]:
        response = await self._openai.embeddings.create(
            input=text,
            model=self.EMBED_MODEL,
        )
        return response.data[0].embedding
