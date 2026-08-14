import logging
import uuid
from datetime import datetime
from openai import AsyncOpenAI

logger = logging.getLogger("call_copilot.rag.chroma_store")


class RAGStore:
    """ChromaDB-backed segment store with OpenAI embeddings.

    chromadb is imported lazily so the app can start (and a call can run
    without live RAG) even when it isn't installed — matches the other
    soft-dependency guards in this codebase (OpenAI-optional embedding)."""

    EMBED_MODEL = "text-embedding-3-small"

    def __init__(self, session_id: str, openai_client: AsyncOpenAI, persist_dir: str = "data/chroma"):
        self._openai = openai_client
        self.session_id = session_id
        self.collection_name = f"call_{session_id}"
        self._collection = None
        try:
            import chromadb
        except ImportError:
            logger.warning("chromadb no está instalado — RAG en vivo deshabilitado para esta llamada.")
            return
        client = chromadb.PersistentClient(path=persist_dir)
        self._collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_segment(self, text: str, timestamp: str | None = None) -> None:
        if self._collection is None or not text.strip():
            return
        embedding = await self._embed(text)
        self._collection.add(
            ids=[str(uuid.uuid4())],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"timestamp": timestamp or datetime.now().isoformat()}],
        )

    async def search(self, query: str, top_k: int = 5) -> list[str]:
        if self._collection is None or not query.strip():
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
