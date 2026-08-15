from __future__ import annotations

import io

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from .base import DocumentLoader


class DocxLoader(DocumentLoader):
    """Extracts paragraphs, headings, and table cell text using python-docx.
    Headings are prefixed with '#' markers (matching Markdown-style heading
    syntax) so the chunker's heading-boundary detection (app/chunking.py) works
    uniformly across DOCX and Markdown sources.
    """

    def extract_text(self, data: bytes) -> str:
        try:
            document = Document(io.BytesIO(data))
        except (PackageNotFoundError, Exception) as exc:
            raise ValueError(f"could not read DOCX: {exc}") from exc

        parts: list[str] = []

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
            if "heading" in style_name or "title" in style_name:
                parts.append(f"# {text}")
            else:
                parts.append(text)

        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))

        if not parts:
            raise ValueError("no extractable text found in DOCX")

        return "\n\n".join(parts)
