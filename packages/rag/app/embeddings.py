"""EmbeddingProvider abstraction.

    EmbeddingProvider
    +-- LocalEmbeddingProvider   (sentence-transformers, runs on-CPU — active)
    +-- FutureCloudEmbeddingProvider   (not implemented; placeholder for later)

Model choice: `sentence-transformers/all-MiniLM-L6-v2`.

Why: it's the standard small/fast sentence-embedding model — 384 dimensions,
~90MB, and encodes a couple of sentences in ~25ms on CPU on this machine
(measured during Step 9 development; see docs/progress.md). It needs no GPU, no
ONNX export step, and no API key, which matches the "local embedding model...
knowledge-base creation remains local and free" requirement directly. A true
ONNX-exported variant would shave startup/inference time further, but the
plain sentence-transformers path was chosen for Phase 1 to avoid an extra
export/conversion step; swapping to an ONNX runtime later only requires a new
EmbeddingProvider implementation, not any change to the chunking/vector-store/
retriever code around it.

This module never calls an LLM to generate embeddings — `sentence-transformers`
loads its own dedicated embedding model, not a chat/completion model.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger("rag.embeddings")


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    """Loads the sentence-transformers model once and reuses it. Model loading
    is the slow part (dominated by a one-time download to the local HuggingFace
    cache on first run); subsequent encodes are fast."""

    def __init__(self, model_name: str, dimension: int, torch_threads: int = 4, batch_size: int = 32) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._model = None
        # Hardware-tier-driven (see docs/performance-tuning.md's RAG sweep):
        # embedding throughput scaled close to linearly with torch thread
        # count (~66-82ms/chunk at 1 thread down to ~24-25ms/chunk at 8) on
        # the benchmark machine, while batch size had no measurable latency
        # effect at a fixed thread count — only memory (+~90MB from batch
        # 16 to 64). torch_threads is therefore the tier-scaled lever;
        # batch_size is capped at a modest value on every tier.
        self._torch_threads = torch_threads
        self._batch_size = batch_size

    def _ensure_loaded(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(self._torch_threads)
            logger.info(
                "[EMBEDDING] loading model=%s torch_threads=%d batch_size=%d",
                self._model_name, self._torch_threads, self._batch_size,
            )
            self._model = SentenceTransformer(self._model_name)
            logger.info("[EMBEDDING] model loaded")
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._ensure_loaded()
        # STT/RAG scheduling coordination (Phase B — see app/throttle.py's
        # module doc): yields to active STT on low-end hardware immediately
        # before the CPU-heavy encode call, never around model loading or
        # anything upstream of this. A no-op (returns immediately) unless
        # Rust has actively signaled STT is running on Entry/Standard tier
        # hardware — high-end machines and idle sessions never wait here.
        from app.throttle import wait_while_throttled

        wait_while_throttled()
        vectors = model.encode(
            texts, convert_to_numpy=True, show_progress_bar=False, batch_size=self._batch_size
        )
        return [vector.tolist() for vector in vectors]


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        from app.core.config import get_settings

        settings = get_settings()
        _provider = LocalEmbeddingProvider(
            settings.embedding_model,
            settings.embedding_dim,
            torch_threads=settings.torch_threads,
            batch_size=settings.embed_batch_size,
        )
    return _provider
