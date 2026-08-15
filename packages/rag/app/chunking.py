"""Chunking: splits cleaned document text into overlapping chunks sized for
embedding, preferring natural boundaries over blind character splitting.

Boundary preference, in order: heading > paragraph > sentence > hard cutoff.
Token counts are approximated as whitespace-delimited words (no tokenizer
dependency needed for a size heuristic — good enough to hit the ~500-800 token
target without pulling in a model-specific tokenizer here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass
class RawChunk:
    text: str
    section: Optional[str]
    index: int


def _approx_token_count(text: str) -> int:
    return len(text.split())


def _split_into_sections(text: str) -> List[tuple[Optional[str], str]]:
    """Splits on heading lines, returning (heading_or_None, section_body) pairs.
    A document with no headings becomes a single section with heading=None.
    """
    lines = text.split("\n")
    sections: List[tuple[Optional[str], List[str]]] = []
    current_heading: Optional[str] = None
    current_body: List[str] = []

    for line in lines:
        match = _HEADING_RE.match(line.strip())
        if match:
            if current_body or current_heading is not None:
                sections.append((current_heading, current_body))
            current_heading = match.group(1).strip()
            current_body = []
        else:
            current_body.append(line)

    sections.append((current_heading, current_body))
    return [(heading, "\n".join(body).strip()) for heading, body in sections if "\n".join(body).strip() or heading]


def _split_paragraphs(text: str) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs


def _split_sentences(paragraph: str) -> List[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    return sentences if sentences else [paragraph]


def chunk_text(
    text: str,
    chunk_size_tokens: int = 650,
    overlap_tokens: int = 80,
) -> List[RawChunk]:
    """Greedily packs paragraphs (falling back to sentences, then hard slicing
    for a single paragraph/sentence that alone exceeds chunk_size_tokens) into
    chunks up to `chunk_size_tokens`, carrying `overlap_tokens` worth of trailing
    content from the previous chunk into the next one for retrieval context
    continuity across chunk boundaries.
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[RawChunk] = []
    chunk_index = 0

    for heading, section_text in _split_into_sections(text):
        if not section_text:
            continue

        units: List[str] = []
        for paragraph in _split_paragraphs(section_text):
            if _approx_token_count(paragraph) <= chunk_size_tokens:
                units.append(paragraph)
            else:
                units.extend(_split_sentences(paragraph))

        current_words: List[str] = []
        for unit in units:
            unit_words = unit.split()

            if len(unit_words) > chunk_size_tokens:
                # A single unit alone exceeds the target size (e.g. one huge
                # unbroken sentence/paragraph) — hard-slice it.
                if current_words:
                    chunks.append(RawChunk(" ".join(current_words), heading, chunk_index))
                    chunk_index += 1
                    current_words = []
                for start in range(0, len(unit_words), chunk_size_tokens):
                    piece = unit_words[start : start + chunk_size_tokens]
                    chunks.append(RawChunk(" ".join(piece), heading, chunk_index))
                    chunk_index += 1
                continue

            if len(current_words) + len(unit_words) > chunk_size_tokens and current_words:
                chunks.append(RawChunk(" ".join(current_words), heading, chunk_index))
                chunk_index += 1
                overlap = current_words[-overlap_tokens:] if overlap_tokens > 0 else []
                current_words = list(overlap)

            current_words.extend(unit_words)

        if current_words:
            chunks.append(RawChunk(" ".join(current_words), heading, chunk_index))
            chunk_index += 1
            current_words = []

    return chunks
