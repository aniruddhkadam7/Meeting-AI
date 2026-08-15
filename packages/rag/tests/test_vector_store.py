import time

import pytest

from app.models import Chunk, DocumentMetadata, DocumentType
from app.vector_store import VectorStore

DIM = 8


def _fake_embedding(seed: float) -> list[float]:
    return [seed] * DIM


@pytest.fixture
def store(tmp_path):
    vs = VectorStore(tmp_path / "test.db", DIM)
    yield vs
    vs.close()


def _make_doc(document_id="doc_1", content_hash="hash1") -> DocumentMetadata:
    now = time.time()
    return DocumentMetadata(
        document_id=document_id,
        filename="resume.pdf",
        document_type=DocumentType.RESUME,
        file_size=1000,
        content_hash=content_hash,
        created_at=now,
        updated_at=now,
    )


def test_insert_and_list_document(store):
    doc = _make_doc()
    store.upsert_document(doc)
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0]["document_id"] == "doc_1"


def test_find_document_by_hash(store):
    doc = _make_doc(content_hash="abc123")
    store.upsert_document(doc)
    found = store.find_document_by_hash("abc123")
    assert found is not None
    assert found["document_id"] == doc.document_id

    not_found = store.find_document_by_hash("does-not-exist")
    assert not_found is None


def test_insert_chunks_and_search(store):
    doc = _make_doc()
    store.upsert_document(doc)

    chunks = [
        Chunk("chunk_1", doc.document_id, DocumentType.RESUME, "resume.pdf", 0, "I built a RAG system."),
        Chunk("chunk_2", doc.document_id, DocumentType.RESUME, "resume.pdf", 1, "I used FastAPI and Docker."),
    ]
    embeddings = [_fake_embedding(1.0), _fake_embedding(5.0)]
    store.insert_chunks(chunks, embeddings)

    results = store.search(_fake_embedding(1.0), top_k=2)
    assert len(results) == 2
    # The chunk whose embedding exactly matches the query should rank first.
    assert results[0].chunk_id == "chunk_1"
    assert results[0].text == "I built a RAG system."


def test_delete_document_removes_its_chunks(store):
    doc = _make_doc()
    store.upsert_document(doc)
    chunks = [Chunk("chunk_1", doc.document_id, DocumentType.RESUME, "resume.pdf", 0, "text")]
    store.insert_chunks(chunks, [_fake_embedding(1.0)])

    store.delete_document(doc.document_id)

    assert store.list_documents() == []
    results = store.search(_fake_embedding(1.0), top_k=5)
    assert results == []


def test_clear_all_removes_everything(store):
    doc1 = _make_doc("doc_1", "hash1")
    doc2 = _make_doc("doc_2", "hash2")
    store.upsert_document(doc1)
    store.upsert_document(doc2)
    store.insert_chunks(
        [Chunk("chunk_1", "doc_1", DocumentType.RESUME, "a.pdf", 0, "text a")],
        [_fake_embedding(1.0)],
    )

    store.clear_all()

    assert store.list_documents() == []
    doc_count, chunk_count = store.counts()
    assert doc_count == 0
    assert chunk_count == 0


def test_counts_reflect_inserted_data(store):
    doc = _make_doc()
    store.upsert_document(doc)
    chunks = [
        Chunk("chunk_1", doc.document_id, DocumentType.RESUME, "resume.pdf", 0, "a"),
        Chunk("chunk_2", doc.document_id, DocumentType.RESUME, "resume.pdf", 1, "b"),
    ]
    store.insert_chunks(chunks, [_fake_embedding(1.0), _fake_embedding(2.0)])

    doc_count, chunk_count = store.counts()
    assert doc_count == 1
    assert chunk_count == 2


def test_search_on_empty_store_returns_no_results(store):
    results = store.search(_fake_embedding(1.0), top_k=5)
    assert results == []


def _make_agent_doc(agent_id, document_id, content_hash) -> DocumentMetadata:
    now = time.time()
    return DocumentMetadata(
        document_id=document_id,
        filename="notes.txt",
        document_type=DocumentType.OTHER,
        file_size=10,
        content_hash=content_hash,
        created_at=now,
        updated_at=now,
        agent_id=agent_id,
    )


def test_list_documents_is_scoped_by_agent_id(store):
    store.upsert_document(_make_doc("doc_global", "hash_global"))
    store.upsert_document(_make_agent_doc("agent_a", "doc_a", "hash_a"))
    store.upsert_document(_make_agent_doc("agent_b", "doc_b", "hash_b"))

    assert [d["document_id"] for d in store.list_documents()] == ["doc_global"]
    assert [d["document_id"] for d in store.list_documents(agent_id="agent_a")] == ["doc_a"]
    assert [d["document_id"] for d in store.list_documents(agent_id="agent_b")] == ["doc_b"]


def test_find_document_by_hash_does_not_cross_agent_scopes(store):
    store.upsert_document(_make_agent_doc("agent_a", "doc_a", "same_hash"))

    assert store.find_document_by_hash("same_hash", agent_id="agent_a") is not None
    assert store.find_document_by_hash("same_hash", agent_id="agent_b") is None
    assert store.find_document_by_hash("same_hash") is None


def test_search_is_scoped_by_agent_id(store):
    store.upsert_document(_make_agent_doc("agent_a", "doc_a", "hash_a"))
    store.upsert_document(_make_agent_doc("agent_b", "doc_b", "hash_b"))
    store.insert_chunks(
        [Chunk("chunk_a", "doc_a", DocumentType.OTHER, "notes.txt", 0, "agent a content", agent_id="agent_a")],
        [_fake_embedding(1.0)],
    )
    store.insert_chunks(
        [Chunk("chunk_b", "doc_b", DocumentType.OTHER, "notes.txt", 0, "agent b content", agent_id="agent_b")],
        [_fake_embedding(1.0)],
    )

    results_a = store.search(_fake_embedding(1.0), top_k=5, agent_id="agent_a")
    assert [r.chunk_id for r in results_a] == ["chunk_a"]

    results_b = store.search(_fake_embedding(1.0), top_k=5, agent_id="agent_b")
    assert [r.chunk_id for r in results_b] == ["chunk_b"]

    # The pre-existing unscoped search must never leak agent-scoped chunks.
    assert store.search(_fake_embedding(1.0), top_k=5) == []


def test_clear_all_only_clears_its_own_scope(store):
    store.upsert_document(_make_doc("doc_global", "hash_global"))
    store.upsert_document(_make_agent_doc("agent_a", "doc_a", "hash_a"))

    store.clear_all(agent_id="agent_a")

    assert [d["document_id"] for d in store.list_documents()] == ["doc_global"]
    assert store.list_documents(agent_id="agent_a") == []


def test_counts_are_scoped_by_agent_id(store):
    store.upsert_document(_make_doc("doc_global", "hash_global"))
    store.upsert_document(_make_agent_doc("agent_a", "doc_a", "hash_a"))

    global_docs, _ = store.counts()
    agent_docs, _ = store.counts(agent_id="agent_a")
    assert global_docs == 1
    assert agent_docs == 1


def test_opening_a_pre_agent_scoping_database_migrates_in_place(tmp_path):
    """A real user's existing knowledge.db, created before agent_id existed,
    has `documents`/`chunks` tables without that column. VectorStore.__init__
    must ALTER TABLE them in place rather than crashing (CREATE TABLE IF NOT
    EXISTS in the schema script is a no-op against an already-existing table
    with the old shape) — this is the exact bug caught manually while
    building this feature: creating the agent_id indexes before running the
    ALTER TABLE migration failed with "no such column: agent_id"."""
    import sqlite3

    import sqlite_vec

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(
        """
        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY, filename TEXT, document_type TEXT,
            file_size INTEGER, content_hash TEXT, created_at REAL, updated_at REAL,
            status TEXT, chunk_count INTEGER DEFAULT 0, error_message TEXT
        );
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, rowid_key INTEGER UNIQUE, document_id TEXT,
            document_type TEXT, filename TEXT, chunk_index INTEGER, text TEXT, section TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO documents VALUES ('doc1','a.txt','OTHER',10,'h1',1.0,1.0,'READY',0,NULL)"
    )
    conn.commit()
    conn.close()

    vs = VectorStore(db_path, DIM)
    try:
        docs = vs.list_documents()
        assert len(docs) == 1
        assert docs[0]["document_id"] == "doc1"
        assert "agent_id" in docs[0].keys()
    finally:
        vs.close()
