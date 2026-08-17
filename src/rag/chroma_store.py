import logging
import uuid
from datetime import datetime
from openai import AsyncOpenAI

from src.rag.base import ChromaEmbeddingStore

logger = logging.getLogger("call_copilot.rag.chroma_store")


class RAGStore(ChromaEmbeddingStore):
    """ChromaDB-backed segment store with OpenAI embeddings, scoped to one
    call session (collection is discarded with the session)."""

    def __init__(self, session_id: str, openai_client: AsyncOpenAI, persist_dir: str | None = None):
        self.session_id = session_id
        self.collection_name = f"call_{session_id}"
        super().__init__(
            openai_client,
            collection_name=self.collection_name,
            logger=logger,
            disabled_log_msg="chromadb no está instalado — RAG en vivo deshabilitado para esta llamada.",
            persist_dir=persist_dir,
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
