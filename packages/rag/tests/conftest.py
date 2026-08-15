import pytest

from app.core.config import Settings
from app.embeddings import EmbeddingProvider
from app.pipeline import KnowledgeBaseService
from app.vector_store import VectorStore

FAKE_DIM = 16


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic hash-based fake embeddings for tests that don't need real
    semantic quality (pipeline/API-level tests) — keeps the suite fast and
    avoids downloading/loading the real model for tests that aren't actually
    verifying retrieval relevance (see test_retrieval_quality.py for that)."""

    @property
    def dimension(self) -> int:
        return FAKE_DIM

    def embed(self, texts):
        vectors = []
        for text in texts:
            seed = sum(ord(c) for c in text) % 1000
            vectors.append([((seed + i) % 100) / 100.0 for i in range(FAKE_DIM)])
        return vectors


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.data_dir = tmp_path / "knowledge"
    s.embedding_dim = FAKE_DIM
    s.chunk_size_tokens = 100
    s.chunk_overlap_tokens = 10
    s.max_document_size_mb = 25
    s.ensure_dirs()
    return s


@pytest.fixture
def knowledge_base(settings):
    store = VectorStore(settings.vector_store_path, settings.embedding_dim)
    kb = KnowledgeBaseService(settings, store, FakeEmbeddingProvider())
    yield kb
    store.close()
