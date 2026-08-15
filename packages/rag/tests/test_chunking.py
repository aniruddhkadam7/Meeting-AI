from app.chunking import chunk_text


def test_empty_document_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_document_produces_single_chunk():
    text = "This is a short paragraph about a project."
    chunks = chunk_text(text, chunk_size_tokens=650, overlap_tokens=80)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].index == 0


def test_heading_boundaries_are_tracked_as_sections():
    text = "# Architecture\n\nWe used FastAPI and pgvector.\n\n# Deployment\n\nWe used Docker."
    chunks = chunk_text(text, chunk_size_tokens=650, overlap_tokens=80)
    sections = {c.section for c in chunks}
    assert "Architecture" in sections
    assert "Deployment" in sections


def test_long_document_splits_into_multiple_chunks_with_overlap():
    # Build a document well over the chunk size so it must split.
    paragraph = " ".join([f"word{i}" for i in range(100)])
    text = "\n\n".join([paragraph] * 20)  # ~2000 words total
    chunks = chunk_text(text, chunk_size_tokens=300, overlap_tokens=30)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text.split()) <= 300 + 30  # allow for overlap carryover


def test_overlap_carries_trailing_words_into_next_chunk():
    paragraph = " ".join([f"word{i}" for i in range(50)])
    text = "\n\n".join([paragraph] * 10)
    chunks = chunk_text(text, chunk_size_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    # The tail of chunk N should reappear at the head of chunk N+1.
    first_chunk_tail = chunks[0].text.split()[-10:]
    second_chunk_head = chunks[1].text.split()[:30]
    assert any(word in second_chunk_head for word in first_chunk_tail)


def test_single_oversized_paragraph_is_hard_sliced():
    huge_paragraph = " ".join([f"word{i}" for i in range(1000)])
    chunks = chunk_text(huge_paragraph, chunk_size_tokens=200, overlap_tokens=0)
    assert len(chunks) >= 5
    for chunk in chunks:
        assert len(chunk.text.split()) <= 200


def test_chunk_indices_are_sequential():
    paragraph = " ".join([f"word{i}" for i in range(100)])
    text = "\n\n".join([paragraph] * 10)
    chunks = chunk_text(text, chunk_size_tokens=150, overlap_tokens=20)
    indices = [c.index for c in chunks]
    assert indices == list(range(len(chunks)))
