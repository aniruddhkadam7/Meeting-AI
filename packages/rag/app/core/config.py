"""Local RAG service configuration.

All state (raw documents, extracted text, chunks, the vector store) lives under
the user's local AppData directory — never inside the source repository, and
never uploaded anywhere. See docs/architecture.md for the full directory layout.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "InterviewAssistant" / "knowledge"
    return Path.home() / ".interview-assistant" / "knowledge"


class Settings:
    host: str = os.getenv("RAG_HOST", "127.0.0.1")
    port: int = int(os.getenv("RAG_PORT", "8100"))

    data_dir: Path = Path(os.getenv("RAG_DATA_DIR", str(_default_data_dir())))

    max_document_size_mb: int = int(os.getenv("MAX_DOCUMENT_SIZE_MB", "25"))

    embedding_model: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "384"))

    chunk_size_tokens: int = int(os.getenv("CHUNK_SIZE_TOKENS", "650"))
    chunk_overlap_tokens: int = int(os.getenv("CHUNK_OVERLAP_TOKENS", "80"))

    # Hardware-tier-driven (see apps/desktop/src-tauri/src/hardware/manager.rs
    # and docs/performance-tuning.md's RAG sweep). Read once at process
    # startup like everything else in this class — a performance-mode change
    # that alters these requires restarting this service, since torch's
    # thread count and this class's values are both fixed after first use.
    # Defaults (4 threads, batch 32) match this file's pre-tiering behavior:
    # torch's own default thread count on the benchmark machine, and
    # sentence-transformers' library default batch size.
    embed_batch_size: int = int(os.getenv("RAG_EMBED_BATCH_SIZE", "32"))
    torch_threads: int = int(os.getenv("RAG_TORCH_THREADS", "4"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def max_document_size_bytes(self) -> int:
        return self.max_document_size_mb * 1024 * 1024

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def extracted_dir(self) -> Path:
        return self.data_dir / "extracted"

    @property
    def vector_store_path(self) -> Path:
        return self.data_dir / "vector_store" / "knowledge.db"

    def ensure_dirs(self) -> None:
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
