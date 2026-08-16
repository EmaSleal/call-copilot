"""
Shared boilerplate for the Chroma-backed embedding stores in this package
(RAGStore, ToolsCatalogStore, SegmentsSearchStore, CategoriesStore). Each one
owns a different collection, id scheme, and search return shape — only the
chromadb connection setup and the OpenAI embedding call were duplicated
across all four.
"""

import logging

from openai import AsyncOpenAI

from src.core.paths import app_home


class ChromaEmbeddingStore:
    EMBED_MODEL = "text-embedding-3-small"

    def __init__(
        self,
        openai_client: AsyncOpenAI | None,
        collection_name: str,
        logger: logging.Logger,
        disabled_log_msg: str,
        persist_dir: str | None = None,
    ):
        persist_dir = persist_dir or str(app_home() / "data" / "chroma")
        self._openai = openai_client
        self._collection = None
        try:
            import chromadb
        except ImportError:
            logger.warning(disabled_log_msg)
            return
        client = chromadb.PersistentClient(path=persist_dir)
        self._collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def _embed(self, text: str) -> list[float]:
        response = await self._openai.embeddings.create(
            input=text,
            model=self.EMBED_MODEL,
        )
        return response.data[0].embedding
