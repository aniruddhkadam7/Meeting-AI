"""Retriever: search(query, top_k) -> ranked chunks.

Semantic-only for Phase 1 (embed the query, vector search). The interface is
kept narrow and single-purpose so a later hybrid-search implementation
(semantic + keyword + metadata filtering + reranking, per spec section 14) can
wrap or replace this without changing callers — callers only ever see
`search(query, top_k) -> List[SearchResult]`.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from app.embeddings import EmbeddingProvider
from app.models import SearchResult
from app.vector_store import VectorStore

logger = logging.getLogger("rag.retriever")


class Retriever:
    def __init__(self, vector_store: VectorStore, embedding_provider: EmbeddingProvider) -> None:
        self._vector_store = vector_store
        self._embeddings = embedding_provider

    def search(
        self, query: str, top_k: int = 5, agent_id: Optional[str] = None
    ) -> tuple[List[SearchResult], float]:
        """Returns (results, latency_ms). `agent_id=None` searches the
        original global/unscoped knowledge base (Interview/Sales/Consulting
        Mode); passing an agent's id scopes the search to that Custom
        Agent's own uploaded documents only."""
        start = time.perf_counter()
        query_embedding = self._embeddings.embed([query])[0]
        results = self._vector_store.search(query_embedding, top_k, agent_id=agent_id)
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[RETRIEVAL] query_len=%d top_k=%d results=%d latency_ms=%.1f",
            len(query),
            top_k,
            len(results),
            latency_ms,
        )
        return results, latency_ms
