from app.text_cleaning import clean_text


def test_collapses_excess_blank_lines():
    text = "Paragraph one.\n\n\n\n\nParagraph two."
    result = clean_text(text)
    assert "\n\n\n" not in result
    assert "Paragraph one." in result
    assert "Paragraph two." in result


def test_strips_trailing_whitespace_on_lines():
    text = "Line one.   \nLine two.\t\n"
    result = clean_text(text)
    assert "   \n" not in result
    assert "\t\n" not in result


def test_collapses_multiple_spaces():
    text = "This   has    extra     spaces."
    result = clean_text(text)
    assert "  " not in result


def test_preserves_technical_tokens():
    text = "Skills: C++, C#, .NET, AWS Lambda, Node.js"
    result = clean_text(text)
    assert "C++" in result
    assert "C#" in result
    assert ".NET" in result
    assert "AWS Lambda" in result
    assert "Node.js" in result


def test_joins_pdf_wrapped_lines():
    # A common PDF-extraction artifact: a sentence broken mid-word-boundary
    # across lines with no real paragraph break.
    text = "I built a RAG system using\nsemantic search and embeddings."
    result = clean_text(text)
    assert "RAG system using semantic search" in result


def test_preserves_intentional_paragraph_breaks():
    text = "First paragraph here.\n\nSecond paragraph here."
    result = clean_text(text)
    assert "\n\n" in result


def test_empty_input_returns_empty_string():
    assert clean_text("") == ""


def test_whitespace_only_input_returns_empty_string():
    assert clean_text("   \n\n\t  ") == ""
