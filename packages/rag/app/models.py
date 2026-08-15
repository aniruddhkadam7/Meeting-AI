"""Core data models for the local RAG pipeline.

Everything here is process-local: documents, chunks, and embeddings never leave
this machine, and this module has no HTTP client of its own — see
docs/architecture.md for the full local/backend boundary. This service is
entirely separate from apps/backend (the FastAPI analysis service); the two only
interact because the desktop app calls both.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class DocumentType(str, Enum):
    RESUME = "RESUME"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"
    PROJECT = "PROJECT"
    COMPANY = "COMPANY"
    INTERVIEW_PREPARATION = "INTERVIEW_PREPARATION"
    TECHNICAL_NOTES = "TECHNICAL_NOTES"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    UPLOADING = "UPLOADING"
    EXTRACTING = "EXTRACTING"
    CLEANING = "CLEANING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    ERROR = "ERROR"


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}

# MIME types accepted per extension. Checked where the client supplies one, but
# the extension is the authoritative check (browsers/OS MIME sniffing is
# unreliable) — see loaders/__init__.py::validate_file.
ACCEPTED_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain", "text/x-markdown"},
    ".markdown": {"text/markdown", "text/plain", "text/x-markdown"},
}


def compute_content_hash(data: bytes) -> str:
    """SHA-256 of raw file bytes, used to detect duplicate uploads without
    re-running extraction/chunking/embedding on an identical file."""
    return hashlib.sha256(data).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class DocumentMetadata:
    document_id: str
    filename: str
    document_type: DocumentType
    file_size: int
    content_hash: str
    created_at: float
    updated_at: float
    status: DocumentStatus = DocumentStatus.UPLOADING
    chunk_count: int = 0
    error_message: Optional[str] = None
    # None = the original global/unscoped knowledge base (Interview/Sales/
    # Consulting Mode's shared KB). Set to an agent's id to scope a document
    # to that Custom Agent's own workspace — see vector_store.py.
    agent_id: Optional[str] = None

    @staticmethod
    def create(
        filename: str,
        document_type: DocumentType,
        file_size: int,
        content_hash: str,
        agent_id: Optional[str] = None,
    ) -> "DocumentMetadata":
        now = time.time()
        return DocumentMetadata(
            document_id=new_id("doc"),
            filename=filename,
            document_type=document_type,
            file_size=file_size,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
            agent_id=agent_id,
        )


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    document_type: DocumentType
    filename: str
    chunk_index: int
    text: str
    section: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    text: str
    filename: str
    document_type: DocumentType


def validate_extension(path: Path) -> str:
    """Returns the lowercase extension if supported, raises ValueError otherwise."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported file extension '{ext}' (supported: {supported})")
    return ext
