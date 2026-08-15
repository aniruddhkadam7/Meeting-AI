"""DocumentLoader abstraction. Each loader turns raw file bytes into plain text,
attempting to preserve structural cues (headings, paragraph breaks) that the
chunker later uses to find good split points — see app/chunking.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DocumentLoader(ABC):
    @abstractmethod
    def extract_text(self, data: bytes) -> str:
        """Extracts text from raw file bytes. Raises ValueError on corrupt/
        unreadable content — callers should catch this and mark the document
        ERROR rather than crash the pipeline."""
        raise NotImplementedError
