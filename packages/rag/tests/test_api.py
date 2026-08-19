import io

from fastapi.testclient import TestClient

import app.state as app_state
from app.main import app
from app.pipeline import KnowledgeBaseService
from app.retriever import Retriever
from app.vector_store import VectorStore
from tests.conftest import FAKE_DIM, FakeEmbeddingProvider


def _isolated_client(tmp_path):
    from app.core.config import Settings

    settings = Settings()
    settings.data_dir = tmp_path / "knowledge"
    settings.embedding_dim = FAKE_DIM
    settings.chunk_size_tokens = 100
    settings.chunk_overlap_tokens = 10
    settings.ensure_dirs()

    store = VectorStore(settings.vector_store_path, settings.embedding_dim)
    provider = FakeEmbeddingProvider()

    app_state._vector_store = store
    app_state._knowledge_base = KnowledgeBaseService(settings, store, provider)
    app_state._retriever = Retriever(store, provider)

    return TestClient(app)


def test_health(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_list_and_search(tmp_path):
    client = _isolated_client(tmp_path)

    upload_response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", io.BytesIO(b"I implemented a RAG pipeline with local embeddings."), "text/plain")},
        data={"document_type": "TECHNICAL_NOTES"},
    )
    assert upload_response.status_code == 200
    body = upload_response.json()
    assert body["status"] == "READY"
    assert body["chunk_count"] >= 1

    list_response = client.get("/documents")
    assert list_response.status_code == 200
    assert len(list_response.json()["documents"]) == 1

    search_response = client.post("/search", json={"query": "RAG pipeline", "top_k": 3})
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert "results" in search_body
    assert "latency_ms" in search_body


def test_upload_rejects_unsupported_extension(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.post(
        "/documents/upload",
        files={"file": ("image.png", io.BytesIO(b"binary"), "image/png")},
        data={"document_type": "OTHER"},
    )
    assert response.status_code == 422


def test_delete_document(tmp_path):
    client = _isolated_client(tmp_path)
    upload_response = client.post(
        "/documents/upload",
        files={"file": ("a.txt", io.BytesIO(b"Some content to delete later."), "text/plain")},
        data={"document_type": "OTHER"},
    )
    document_id = upload_response.json()["document_id"]

    delete_response = client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 200

    list_response = client.get("/documents")
    assert list_response.json()["documents"] == []


def test_internal_throttle_route_activates_and_deactivates(tmp_path):
    """STT/RAG scheduling coordination (Phase B) — the internal endpoint
    Rust calls to signal STT is active/inactive on low-end hardware."""
    import app.throttle as throttle_module

    client = _isolated_client(tmp_path)
    try:
        response = client.post("/internal/throttle", json={"active": True})
        assert response.status_code == 200
        assert response.json()["active"] is True
        assert throttle_module.is_active() is True

        response = client.post("/internal/throttle", json={"active": False})
        assert response.status_code == 200
        assert response.json()["active"] is False
        assert throttle_module.is_active() is False
    finally:
        throttle_module.set_active(False)  # don't leak state into other tests


def test_search_is_never_throttled_even_while_stt_is_active(tmp_path):
    """Requirement: active retrieval for a user question must NEVER be
    affected by the STT throttle — only indexing (the embedding step inside
    document upload) yields. This test proves /search's own request path
    never calls wait_while_throttled() at all: it activates the throttle
    with a deliberately long TTL/no auto-clear and confirms /search still
    returns immediately rather than hanging."""
    import time

    import app.throttle as throttle_module

    client = _isolated_client(tmp_path)
    try:
        client.post(
            "/documents/upload",
            files={"file": ("notes.txt", io.BytesIO(b"Some searchable content about RAG."), "text/plain")},
            data={"document_type": "TECHNICAL_NOTES"},
        )
        throttle_module.set_active(True)  # simulate STT actively running

        started = time.monotonic()
        response = client.post("/search", json={"query": "RAG", "top_k": 3})
        elapsed = time.monotonic() - started

        assert response.status_code == 200
        assert elapsed < 1.0, "search must never wait on the STT throttle"
    finally:
        throttle_module.set_active(False)


def test_clear_knowledge_base(tmp_path):
    client = _isolated_client(tmp_path)
    client.post(
        "/documents/upload",
        files={"file": ("a.txt", io.BytesIO(b"Content here for testing clear."), "text/plain")},
        data={"document_type": "OTHER"},
    )
    response = client.post("/knowledge-base/clear")
    assert response.status_code == 200
    assert client.get("/documents").json()["documents"] == []


def test_knowledge_base_status_endpoint(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.get("/knowledge-base/status")
    assert response.status_code == 200
    assert response.json()["document_count"] == 0


def test_search_with_invalid_top_k_returns_422(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.post("/search", json={"query": "test", "top_k": 0})
    assert response.status_code == 422


def test_search_with_empty_query_returns_422(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.post("/search", json={"query": "", "top_k": 5})
    assert response.status_code == 422


def test_agent_scoped_upload_list_and_search_over_http(tmp_path):
    client = _isolated_client(tmp_path)

    client.post(
        "/documents/upload",
        files={"file": ("global.txt", io.BytesIO(b"Global knowledge base content."), "text/plain")},
        data={"document_type": "OTHER"},
    )
    client.post(
        "/documents/upload",
        files={"file": ("agent.txt", io.BytesIO(b"Agent specific knowledge content."), "text/plain")},
        data={"document_type": "OTHER", "agent_id": "agent_a"},
    )

    assert len(client.get("/documents").json()["documents"]) == 1
    agent_docs = client.get("/documents", params={"agent_id": "agent_a"}).json()["documents"]
    assert len(agent_docs) == 1
    assert agent_docs[0]["filename"] == "agent.txt"

    search_response = client.post(
        "/search", json={"query": "knowledge content", "top_k": 5, "agent_id": "agent_a"}
    )
    assert search_response.status_code == 200
    results = search_response.json()["results"]
    assert len(results) == 1
    assert results[0]["metadata"]["filename"] == "agent.txt"


def test_get_document_text_rejects_malformed_document_id(tmp_path):
    """document_id flows into a filesystem path join (routes.py) — anything
    not matching the doc_<16 hex> format the server itself generates must be
    rejected before it ever reaches Path construction. Security regression
    for the path-traversal/unvalidated-id finding."""
    client = _isolated_client(tmp_path)
    for bad_id in ["../../../etc/passwd", "doc_not-hex!!", "doc_short", "..%2F..%2Fsecret"]:
        response = client.get(f"/documents/{bad_id}/text")
        assert response.status_code == 404


def test_delete_document_rejects_malformed_document_id_and_glob_metacharacters(tmp_path):
    """delete_document uses document_id in a glob() pattern as well as a path
    join — glob wildcards in an unvalidated id could match unintended sibling
    files. Security regression for the glob-injection finding."""
    client = _isolated_client(tmp_path)
    for bad_id in ["doc_*", "doc_????????????????", "../doc_0123456789abcdef"]:
        response = client.delete(f"/documents/{bad_id}")
        assert response.status_code == 404


def test_upload_rejects_oversized_agent_id(tmp_path):
    client = _isolated_client(tmp_path)
    response = client.post(
        "/documents/upload",
        files={"file": ("a.txt", io.BytesIO(b"Some content."), "text/plain")},
        data={"document_type": "OTHER", "agent_id": "x" * 200},
    )
    assert response.status_code == 422


def test_internal_token_required_when_configured(tmp_path, monkeypatch):
    """When the desktop app sets RAG_INTERNAL_TOKEN, every non-/health route
    must reject requests missing (or presenting the wrong) bearer token —
    this is the service's only defense against another local process driving
    it. Security regression for the missing-authentication finding."""
    from app.core.config import get_settings

    client = _isolated_client(tmp_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "internal_auth_token", "secret-token")
    try:
        # No Authorization header at all.
        response = client.post("/internal/throttle", json={"active": True})
        assert response.status_code == 401

        # Wrong token.
        response = client.post(
            "/internal/throttle",
            json={"active": True},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

        # Correct token succeeds.
        response = client.post(
            "/internal/throttle",
            json={"active": True},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert response.status_code == 200

        # /health never requires the token (used for the pre-token readiness poll).
        response = client.get("/health")
        assert response.status_code == 200
    finally:
        import app.throttle as throttle_module

        throttle_module.set_active(False)


def test_clear_knowledge_base_scoped_to_agent_leaves_global_untouched(tmp_path):
    client = _isolated_client(tmp_path)
    client.post(
        "/documents/upload",
        files={"file": ("global.txt", io.BytesIO(b"Global content here."), "text/plain")},
        data={"document_type": "OTHER"},
    )
    client.post(
        "/documents/upload",
        files={"file": ("agent.txt", io.BytesIO(b"Agent content here."), "text/plain")},
        data={"document_type": "OTHER", "agent_id": "agent_a"},
    )

    response = client.post("/knowledge-base/clear", params={"agent_id": "agent_a"})
    assert response.status_code == 200
    assert len(client.get("/documents").json()["documents"]) == 1
    assert client.get("/documents", params={"agent_id": "agent_a"}).json()["documents"] == []
