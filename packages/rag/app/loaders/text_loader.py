from __future__ import annotations

from .base import DocumentLoader


class TxtLoader(DocumentLoader):
    """Plain text — decoded as UTF-8 with a Latin-1 fallback for files that
    aren't valid UTF-8 (common with older exported text)."""

    def extract_text(self, data: bytes) -> str:
        text = _decode(data)
        if not text.strip():
            raise ValueError("text file is empty")
        return text


class MarkdownLoader(DocumentLoader):
    """Markdown is treated as text — headings/structure are already present as
    literal '#' markers, which the chunker's heading-boundary detection reads
    directly, so no extra processing is needed here."""

    def extract_text(self, data: bytes) -> str:
        text = _decode(data)
        if not text.strip():
            raise ValueError("markdown file is empty")
        return text


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")
