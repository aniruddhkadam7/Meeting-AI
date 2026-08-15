"""Document processing pipeline orchestration.

    File -> Validation -> Text Extraction -> Cleaning -> Chunking -> Embedding -> Vector Store

Ties together loaders, text_cleaning, chunking, embeddings, and vector_store
into the single entry point the HTTP API calls. Also owns document storage on
disk (raw file + extracted text, under the user's local AppData directory —
never inside the repo, never uploaded to any backend) and duplicate detection
via content hash.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional

from app.chunking import chunk_text
from app.core.config import Settings
from app.embeddings import EmbeddingProvider
from app.loaders import get_loader
from app.models import (
    Chunk,
    DocumentMetadata,
    DocumentStatus,
    DocumentType,
    compute_content_hash,
    new_id,
    validate_extension,
)
from app.text_cleaning import clean_text
from app.vector_store import VectorStore

logger = logging.getLogger("rag.pipeline")


class DocumentTooLargeError(ValueError):
    pass


class KnowledgeBaseService:
    def __init__(self, settings: Settings, vector_store: VectorStore, embedding_provider: EmbeddingProvider) -> None:
        self._settings = settings
        self._store = vector_store
        self._embeddings = embedding_provider

    def list_documents(self, agent_id: Optional[str] = None) -> List[DocumentMetadata]:
        return [_row_to_metadata(row) for row in self._store.list_documents(agent_id=agent_id)]

    def knowledge_base_status(self, agent_id: Optional[str] = None) -> dict:
        doc_count, chunk_count = self._store.counts(agent_id=agent_id)
        documents = self.list_documents(agent_id=agent_id)
        all_ready = all(d.status == DocumentStatus.READY for d in documents) if documents else True
        return {
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "status": "READY" if all_ready and doc_count > 0 else ("EMPTY" if doc_count == 0 else "PROCESSING"),
        }

    def delete_document(self, document_id: str) -> None:
        self._store.delete_document(document_id)
        extracted_path = self._settings.extracted_dir / f"{document_id}.txt"
        raw_paths = list(self._settings.documents_dir.glob(f"{document_id}.*"))
        for path in [extracted_path, *raw_paths]:
            if path.exists():
                path.unlink()

    def clear_all(self, agent_id: Optional[str] = None) -> None:
        # Deletes only this scope's documents (raw file + extracted text +
        # vector rows) via delete_document, rather than wiping every file
        # under documents_dir/extracted_dir unconditionally — otherwise
        # clearing one agent's knowledge base would delete every other
        # agent's (and the global KB's) files too, since they all share the
        # same on-disk directories.
        for document in self.list_documents(agent_id=agent_id):
            self.delete_document(document.document_id)

    def process_document(
        self, filename: str, data: bytes, document_type: DocumentType, agent_id: Optional[str] = None
    ) -> DocumentMetadata:
        """Runs the full pipeline for one uploaded file. Never logs extracted
        text/document content — only metadata (spec section 18)."""

        if len(data) > self._settings.max_document_size_bytes:
            raise DocumentTooLargeError(
                f"file exceeds the {self._settings.max_document_size_mb}MB limit"
            )

        path = Path(filename)
        extension = validate_extension(path)

        content_hash = compute_content_hash(data)
        existing = self._store.find_document_by_hash(content_hash, agent_id=agent_id)
        if existing is not None and existing["status"] == DocumentStatus.READY.value:
            logger.info("[DOCUMENT] duplicate content_hash=%s... skipping reprocessing", content_hash[:12])
            return _row_to_metadata(existing)

        metadata = DocumentMetadata.create(filename, document_type, len(data), content_hash, agent_id=agent_id)
        metadata.status = DocumentStatus.UPLOADING
        self._store.upsert_document(metadata)

        raw_path = self._settings.documents_dir / f"{metadata.document_id}{extension}"
        raw_path.write_bytes(data)

        try:
            metadata.status = DocumentStatus.EXTRACTING
            self._store.upsert_document(metadata)
            loader = get_loader(extension)
            raw_text = loader.extract_text(data)

            metadata.status = DocumentStatus.CLEANING
            self._store.upsert_document(metadata)
            cleaned = clean_text(raw_text)
            if not cleaned:
                raise ValueError("no usable text remained after cleaning")

            extracted_path = self._settings.extracted_dir / f"{metadata.document_id}.txt"
            extracted_path.write_text(cleaned, encoding="utf-8")

            metadata.status = DocumentStatus.CHUNKING
            self._store.upsert_document(metadata)
            raw_chunks = chunk_text(
                cleaned,
                chunk_size_tokens=self._settings.chunk_size_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
            )
            if not raw_chunks:
                raise ValueError("document produced no chunks")

            chunks = [
                Chunk(
                    chunk_id=new_id("chunk"),
                    document_id=metadata.document_id,
                    document_type=document_type,
                    filename=filename,
                    chunk_index=raw_chunk.index,
                    text=raw_chunk.text,
                    section=raw_chunk.section,
                    agent_id=agent_id,
                )
                for raw_chunk in raw_chunks
            ]

            metadata.status = DocumentStatus.EMBEDDING
            self._store.upsert_document(metadata)
            embeddings = self._embeddings.embed([c.text for c in chunks])

            metadata.status = DocumentStatus.INDEXING
            self._store.upsert_document(metadata)
            self._store.insert_chunks(chunks, embeddings)

            metadata.status = DocumentStatus.READY
            metadata.chunk_count = len(chunks)
            metadata.updated_at = time.time()
            self._store.upsert_document(metadata)

            logger.info(
                "[DOCUMENT] processed document_id=%s chunks=%d status=READY",
                metadata.document_id,
                metadata.chunk_count,
            )
            return metadata

        except Exception as exc:
            metadata.status = DocumentStatus.ERROR
            metadata.error_message = str(exc)
            metadata.updated_at = time.time()
            self._store.upsert_document(metadata)
            logger.error("[DOCUMENT] failed document_id=%s error=%s", metadata.document_id, exc)
            raise


def _row_to_metadata(row) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=row["document_id"],
        filename=row["filename"],
        document_type=DocumentType(row["document_type"]),
        file_size=row["file_size"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=DocumentStatus(row["status"]),
        chunk_count=row["chunk_count"],
        error_message=row["error_message"],
        agent_id=row["agent_id"] if "agent_id" in row.keys() else None,
    )
