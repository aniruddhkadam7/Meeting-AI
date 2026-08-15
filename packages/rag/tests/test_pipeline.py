import pytest

from app.models import DocumentStatus, DocumentType
from app.pipeline import DocumentTooLargeError


def test_process_txt_document_end_to_end(knowledge_base):
    data = b"I built a RAG system using FastAPI, sentence-transformers, and sqlite-vec."
    metadata = knowledge_base.process_document("notes.txt", data, DocumentType.TECHNICAL_NOTES)

    assert metadata.status == DocumentStatus.READY
    assert metadata.chunk_count >= 1
    assert metadata.filename == "notes.txt"

    docs = knowledge_base.list_documents()
    assert len(docs) == 1
    assert docs[0].document_id == metadata.document_id


def test_duplicate_upload_is_not_reprocessed(knowledge_base):
    data = b"Duplicate content for hash testing."
    first = knowledge_base.process_document("a.txt", data, DocumentType.OTHER)
    second = knowledge_base.process_document("a.txt", data, DocumentType.OTHER)

    assert first.document_id == second.document_id
    docs = knowledge_base.list_documents()
    assert len(docs) == 1


def test_file_too_large_is_rejected(knowledge_base):
    knowledge_base._settings.max_document_size_mb = 1  # 1MB limit for this test
    oversized = b"x" * (2 * 1024 * 1024)
    with pytest.raises(DocumentTooLargeError):
        knowledge_base.process_document("big.txt", oversized, DocumentType.OTHER)


def test_unsupported_extension_is_rejected(knowledge_base):
    with pytest.raises(ValueError):
        knowledge_base.process_document("image.png", b"binary data", DocumentType.OTHER)


def test_corrupted_docx_marks_document_as_error(knowledge_base):
    with pytest.raises(ValueError):
        knowledge_base.process_document("bad.docx", b"not a real docx", DocumentType.OTHER)

    docs = knowledge_base.list_documents()
    assert len(docs) == 1
    assert docs[0].status == DocumentStatus.ERROR
    assert docs[0].error_message is not None


def test_empty_document_is_rejected(knowledge_base):
    with pytest.raises(ValueError):
        knowledge_base.process_document("empty.txt", b"", DocumentType.OTHER)


def test_delete_document_removes_it_from_knowledge_base(knowledge_base):
    metadata = knowledge_base.process_document("resume.txt", b"Some resume content here.", DocumentType.RESUME)
    knowledge_base.delete_document(metadata.document_id)
    assert knowledge_base.list_documents() == []


def test_clear_all_empties_knowledge_base(knowledge_base):
    knowledge_base.process_document("a.txt", b"Content A here.", DocumentType.OTHER)
    knowledge_base.process_document("b.txt", b"Content B here.", DocumentType.OTHER)
    knowledge_base.clear_all()
    assert knowledge_base.list_documents() == []


def test_knowledge_base_status_reflects_document_count(knowledge_base):
    status = knowledge_base.knowledge_base_status()
    assert status["document_count"] == 0
    assert status["status"] == "EMPTY"

    knowledge_base.process_document("a.txt", b"Some content here for chunking.", DocumentType.OTHER)
    status = knowledge_base.knowledge_base_status()
    assert status["document_count"] == 1
    assert status["status"] == "READY"


def test_agent_scoped_documents_are_isolated_from_global_and_other_agents(knowledge_base):
    knowledge_base.process_document("global.txt", b"Global KB content here.", DocumentType.OTHER)
    knowledge_base.process_document("a.txt", b"Agent A content here.", DocumentType.OTHER, agent_id="agent_a")
    knowledge_base.process_document("b.txt", b"Agent B content here.", DocumentType.OTHER, agent_id="agent_b")

    assert [d.filename for d in knowledge_base.list_documents()] == ["global.txt"]
    assert [d.filename for d in knowledge_base.list_documents(agent_id="agent_a")] == ["a.txt"]
    assert [d.filename for d in knowledge_base.list_documents(agent_id="agent_b")] == ["b.txt"]


def test_same_content_uploaded_to_two_agents_is_not_deduplicated_across_them(knowledge_base):
    data = b"Identical content uploaded to two different agents."
    first = knowledge_base.process_document("a.txt", data, DocumentType.OTHER, agent_id="agent_a")
    second = knowledge_base.process_document("b.txt", data, DocumentType.OTHER, agent_id="agent_b")

    assert first.document_id != second.document_id
    assert len(knowledge_base.list_documents(agent_id="agent_a")) == 1
    assert len(knowledge_base.list_documents(agent_id="agent_b")) == 1


def test_clear_all_scoped_to_one_agent_leaves_others_and_global_untouched(knowledge_base):
    knowledge_base.process_document("global.txt", b"Global content here.", DocumentType.OTHER)
    knowledge_base.process_document("a.txt", b"Agent A content here.", DocumentType.OTHER, agent_id="agent_a")

    knowledge_base.clear_all(agent_id="agent_a")

    assert len(knowledge_base.list_documents()) == 1
    assert knowledge_base.list_documents(agent_id="agent_a") == []


def test_knowledge_base_status_is_scoped_by_agent_id(knowledge_base):
    knowledge_base.process_document("global.txt", b"Global content here for chunking.", DocumentType.OTHER)
    knowledge_base.process_document(
        "a.txt", b"Agent A content here for chunking.", DocumentType.OTHER, agent_id="agent_a"
    )

    global_status = knowledge_base.knowledge_base_status()
    agent_status = knowledge_base.knowledge_base_status(agent_id="agent_a")
    other_agent_status = knowledge_base.knowledge_base_status(agent_id="agent_b")

    assert global_status["document_count"] == 1
    assert agent_status["document_count"] == 1
    assert other_agent_status["document_count"] == 0
    assert other_agent_status["status"] == "EMPTY"
