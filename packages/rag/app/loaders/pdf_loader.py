from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .base import DocumentLoader

# Bounds pathological page counts (e.g. a small file crafted with thousands of
# near-empty pages) from turning a single upload into an unbounded amount of
# synchronous extraction/embedding work on this single-worker service.
_MAX_PAGES = 2000


class PdfLoader(DocumentLoader):
    """Extracts text page-by-page using pypdf (a maintained, pure-Python PDF
    library — no manual PDF parsing, per spec). Pages are joined with double
    newlines so the chunker can treat page boundaries as paragraph-like breaks.
    """

    def extract_text(self, data: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(data))
        except (PdfReadError, Exception) as exc:  # pypdf raises varied exception types
            raise ValueError(f"could not read PDF: {exc}") from exc

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ValueError(f"PDF is encrypted and could not be opened: {exc}") from exc

        if len(reader.pages) > _MAX_PAGES:
            raise ValueError(f"PDF has too many pages (max {_MAX_PAGES})")

        pages_text = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if text.strip():
                pages_text.append(text)

        if not pages_text:
            raise ValueError("no extractable text found in PDF")

        return "\n\n".join(pages_text)
