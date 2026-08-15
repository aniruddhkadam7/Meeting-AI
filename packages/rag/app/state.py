"""Process-wide singletons for the RAG service: one VectorStore connection and
one embedding provider, shared across requests. Kept simple (module-level
globals) since this is a single-user, single-process local service — no
multi-tenancy, no concurrent-client concerns beyond what SQLite itself handles.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.embeddings import get_embedding_provider
from app.pipeline import KnowledgeBaseService
from app.retriever import Retriever
from app.vector_store import VectorStore

_vector_store: VectorStore | None = None
_knowledge_base: KnowledgeBaseService | None = None
_retriever: Retriever | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        settings = get_settings()
        _vector_store = VectorStore(settings.vector_store_path, settings.embedding_dim)
    return _vector_store


def get_knowledge_base() -> KnowledgeBaseService:
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBaseService(get_settings(), get_vector_store(), get_embedding_provider())
    return _knowledge_base


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever(get_vector_store(), get_embedding_provider())
    return _retriever
