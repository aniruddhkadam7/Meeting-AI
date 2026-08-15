"""Local vector store: SQLite + the sqlite-vec extension.

Chosen over standing up Postgres/pgvector or any cloud vector DB (Pinecone,
Weaviate, Milvus, Qdrant Cloud) because a desktop app should not require the
user to run a database server just to search their own documents. sqlite-vec
is a pure-C, dependency-free SQLite extension (Mozilla Builders project) that
adds a `vec0` virtual table type supporting KNN search directly inside a single
`.db` file — exactly the "SQLite + vector extension" shape the spec suggests,
and it ships prebuilt wheels for Windows so there's no native build step here.

One SQLite connection/file per knowledge base, stored under the user's local
AppData directory (see core/config.py) — never inside the repo, never uploaded.
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import List, Optional

import sqlite_vec

from app.models import Chunk, DocumentType, SearchResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    document_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    agent_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    rowid_key INTEGER NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    section TEXT,
    agent_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_rowid_key ON chunks(rowid_key);
"""

# Indexes on agent_id, created only after _migrate_add_agent_id_columns() has
# guaranteed the column exists on both tables — a pre-existing database file
# created before agent scoping existed has `documents`/`chunks` tables
# without agent_id (CREATE TABLE IF NOT EXISTS in _SCHEMA above is a no-op
# against them), so indexing that column before the ALTER TABLE migration
# runs would fail with "no such column: agent_id".
_AGENT_ID_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_documents_agent_id ON documents(agent_id);
CREATE INDEX IF NOT EXISTS idx_chunks_agent_id ON chunks(agent_id);
"""

# Added to `documents`/`chunks` for pre-existing on-disk databases created
# before agent scoping existed — CREATE TABLE IF NOT EXISTS above only
# applies to brand-new files, so an ALTER TABLE fallback is needed for
# upgrading a real user's existing knowledge.db in place.
_MIGRATE_ADD_AGENT_ID = (
    ("documents", "ALTER TABLE documents ADD COLUMN agent_id TEXT"),
    ("chunks", "ALTER TABLE chunks ADD COLUMN agent_id TEXT"),
)


def _vec_to_blob(vector: List[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class VectorStore:
    def __init__(self, db_path: Path, dimension: int) -> None:
        self._db_path = db_path
        self._dimension = dimension
        self._conn = self._connect()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{self._dimension}])"
        )
        self._migrate_add_agent_id_columns()
        self._conn.executescript(_AGENT_ID_INDEXES)
        self._conn.commit()

    def _migrate_add_agent_id_columns(self) -> None:
        for table, statement in _MIGRATE_ADD_AGENT_ID:
            existing_columns = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "agent_id" not in existing_columns:
                self._conn.execute(statement)

    def close(self) -> None:
        self._conn.close()

    # -- documents -----------------------------------------------------

    def upsert_document(self, metadata) -> None:
        self._conn.execute(
            """
            INSERT INTO documents
                (document_id, filename, document_type, file_size, content_hash,
                 created_at, updated_at, status, chunk_count, error_message, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                filename=excluded.filename,
                document_type=excluded.document_type,
                file_size=excluded.file_size,
                content_hash=excluded.content_hash,
                updated_at=excluded.updated_at,
                status=excluded.status,
                chunk_count=excluded.chunk_count,
                error_message=excluded.error_message,
                agent_id=excluded.agent_id
            """,
            (
                metadata.document_id,
                metadata.filename,
                metadata.document_type.value,
                metadata.file_size,
                metadata.content_hash,
                metadata.created_at,
                metadata.updated_at,
                metadata.status.value,
                metadata.chunk_count,
                metadata.error_message,
                metadata.agent_id,
            ),
        )
        self._conn.commit()

    def find_document_by_hash(self, content_hash: str, agent_id: Optional[str] = None) -> Optional[sqlite3.Row]:
        # Scoped so that uploading the same file to two different agents (or
        # to an agent and the global KB) is never treated as a duplicate of
        # the other's document — each workspace's content is independent.
        if agent_id is None:
            return self._conn.execute(
                "SELECT * FROM documents WHERE content_hash = ? AND agent_id IS NULL", (content_hash,)
            ).fetchone()
        return self._conn.execute(
            "SELECT * FROM documents WHERE content_hash = ? AND agent_id = ?", (content_hash, agent_id)
        ).fetchone()

    def list_documents(self, agent_id: Optional[str] = None) -> List[sqlite3.Row]:
        if agent_id is None:
            return self._conn.execute(
                "SELECT * FROM documents WHERE agent_id IS NULL ORDER BY created_at ASC"
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM documents WHERE agent_id = ? ORDER BY created_at ASC", (agent_id,)
        ).fetchall()

    def get_document(self, document_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()

    def delete_document(self, document_id: str) -> None:
        chunk_ids = [
            row["chunk_id"]
            for row in self._conn.execute(
                "SELECT chunk_id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        for chunk_id in chunk_ids:
            self._conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (_chunk_rowid(chunk_id),))
        self._conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        self._conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
        self._conn.commit()

    def clear_all(self, agent_id: Optional[str] = None) -> None:
        if agent_id is None:
            document_ids = [row["document_id"] for row in self._conn.execute(
                "SELECT document_id FROM documents WHERE agent_id IS NULL"
            ).fetchall()]
        else:
            document_ids = [row["document_id"] for row in self._conn.execute(
                "SELECT document_id FROM documents WHERE agent_id = ?", (agent_id,)
            ).fetchall()]
        for document_id in document_ids:
            self.delete_document(document_id)

    def counts(self, agent_id: Optional[str] = None) -> tuple[int, int]:
        if agent_id is None:
            doc_count = self._conn.execute(
                "SELECT COUNT(*) AS c FROM documents WHERE agent_id IS NULL"
            ).fetchone()["c"]
            chunk_count = self._conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE agent_id IS NULL"
            ).fetchone()["c"]
        else:
            doc_count = self._conn.execute(
                "SELECT COUNT(*) AS c FROM documents WHERE agent_id = ?", (agent_id,)
            ).fetchone()["c"]
            chunk_count = self._conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE agent_id = ?", (agent_id,)
            ).fetchone()["c"]
        return doc_count, chunk_count

    # -- chunks + vectors ------------------------------------------------

    def insert_chunks(self, chunks: List[Chunk], embeddings: List[List[float]]) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            rowid = _chunk_rowid(chunk.chunk_id)
            self._conn.execute(
                """
                INSERT OR REPLACE INTO chunks
                    (chunk_id, rowid_key, document_id, document_type, filename, chunk_index, text, section, agent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id,
                    rowid,
                    chunk.document_id,
                    chunk.document_type.value,
                    chunk.filename,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.section,
                    chunk.agent_id,
                ),
            )
            self._conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (rowid,))
            self._conn.execute(
                "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                (rowid, _vec_to_blob(embedding)),
            )
        self._conn.commit()

    def search(
        self, query_embedding: List[float], top_k: int, agent_id: Optional[str] = None
    ) -> List[SearchResult]:
        # Over-fetch before filtering by agent_id, since vec0's KNN search has
        # no native WHERE-by-metadata support — top_k rows nearest in vector
        # space are pulled first, then narrowed to the requested scope. The
        # multiplier keeps enough candidates that a scoped search still finds
        # top_k real matches even when most of the nearest neighbors overall
        # belong to a different agent/the global KB.
        overfetch = top_k if agent_id is None else max(top_k * 5, 25)
        rows = self._conn.execute(
            """
            SELECT v.rowid AS rowid, v.distance AS distance
            FROM vec_chunks v
            WHERE v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (_vec_to_blob(query_embedding), overfetch),
        ).fetchall()

        results: List[SearchResult] = []
        for row in rows:
            if agent_id is None:
                chunk_row = self._conn.execute(
                    "SELECT * FROM chunks WHERE rowid_key = ? AND agent_id IS NULL", (row["rowid"],)
                ).fetchone()
            else:
                chunk_row = self._conn.execute(
                    "SELECT * FROM chunks WHERE rowid_key = ? AND agent_id = ?", (row["rowid"], agent_id)
                ).fetchone()
            if chunk_row is None:
                continue
            # sqlite-vec returns L2 distance; convert to a 0..1-ish similarity
            # score (1 = identical) for a more intuitive UI display.
            score = 1.0 / (1.0 + row["distance"])
            results.append(
                SearchResult(
                    chunk_id=chunk_row["chunk_id"],
                    score=round(score, 4),
                    text=chunk_row["text"],
                    filename=chunk_row["filename"],
                    document_type=DocumentType(chunk_row["document_type"]),
                )
            )
            if len(results) >= top_k:
                break
        return results


def _chunk_rowid(chunk_id: str) -> int:
    """sqlite-vec's vec0 virtual table keys rows by integer rowid, but our
    chunk ids are strings (see models.new_id). Derives a deterministic rowid
    from a SHA-256 hash of the chunk id (kept within a safe positive 62-bit
    range) rather than an in-memory counter, so the mapping is reproducible
    across process restarts without needing a separate lookup table beyond the
    `rowid_key` column already stored on the `chunks` row."""
    import hashlib

    digest = hashlib.sha256(chunk_id.encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=False) % (2**62)
