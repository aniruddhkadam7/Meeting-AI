from __future__ import annotations

from .base import DocumentLoader
from .docx_loader import DocxLoader
from .pdf_loader import PdfLoader
from .text_loader import MarkdownLoader, TxtLoader

_LOADERS: dict[str, DocumentLoader] = {
    ".pdf": PdfLoader(),
    ".docx": DocxLoader(),
    ".txt": TxtLoader(),
    ".md": MarkdownLoader(),
    ".markdown": MarkdownLoader(),
}


def get_loader(extension: str) -> DocumentLoader:
    loader = _LOADERS.get(extension.lower())
    if loader is None:
        raise ValueError(f"no loader registered for extension '{extension}'")
    return loader


__all__ = ["DocumentLoader", "PdfLoader", "DocxLoader", "TxtLoader", "MarkdownLoader", "get_loader"]
