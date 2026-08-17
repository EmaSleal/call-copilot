"""
Chroma-backed semantic store for cross-session segment search — video
segments AND call segments, keyed by a composite "<source>:<id>" id.
segments.id and call_segments.id are independent sequences that can
collide, same reason unified_segments/Historial already uses composite
"video:N"/"call:N" row keys.
"""

import logging

from openai import AsyncOpenAI

from src.rag.base import ChromaEmbeddingStore

logger = logging.getLogger("call_copilot.rag.segments_store")


class SegmentsSearchStore(ChromaEmbeddingStore):
    COLLECTION = "segments_search"

    def __init__(self, openai_client: AsyncOpenAI | None, persist_dir: str | None = None):
        super().__init__(
            openai_client,
            collection_name=self.COLLECTION,
            logger=logger,
            disabled_log_msg="chromadb no está instalado — búsqueda semántica deshabilitada.",
            persist_dir=persist_dir,
        )

    async def add_segment(self, source: str, segment_id: int, text: str) -> bool:
        """Upsert a segment's embedding, keyed by "<source>:<id>". Returns
        False (no-op) without an OpenAI client, chromadb, or text — never
        raises."""
        if not self._openai or self._collection is None or not text.strip():
            return False
        embedding = await self._embed(text)
        self._collection.upsert(
            ids=[f"{source}:{segment_id}"],
            embeddings=[embedding],
            documents=[text],
        )
        return True

    async def delete_segment(self, source: str, segment_id: int) -> bool:
        """Remove a segment's embedding, keyed by "<source>:<id>". Returns
        False (no-op) without chromadb — never raises."""
        if self._collection is None:
            return False
        self._collection.delete(ids=[f"{source}:{segment_id}"])
        return True

    async def search(self, query: str, top_k: int = 5) -> list[tuple[str, int, float]]:
        """Returns (source, segment_id, distance) tuples ranked by
        similarity."""
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
        parsed: list[tuple[str, int, float]] = []
        for composite_id, distance in zip(ids, distances):
            source, _, raw_id = composite_id.partition(":")
            if raw_id.isdigit():
                parsed.append((source, int(raw_id), distance))
        return parsed
