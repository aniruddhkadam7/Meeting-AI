"""The fixed benchmark corpus.

Every engine is scored against these exact four sentences, spoken once and
replayed byte-identically, so that differences in the measured word error rate
come from the engine and not from a different take of the audio.

`id` is used as the WAV filename stem (`corpus/human/s1.wav`, ...).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sentence:
    id: str
    text: str


SENTENCES: tuple[Sentence, ...] = (
    Sentence(
        "s1",
        "Can you explain the RAG architecture you implemented "
        "and why you selected semantic search?",
    ),
    Sentence(
        "s2",
        "I worked on integrating multiple security tools and used APIs "
        "to collect and normalize security data.",
    ),
    Sentence(
        "s3",
        "How did you handle false positives in your vulnerability "
        "classification model?",
    ),
    Sentence(
        "s4",
        "Can you explain how you deployed the application and how you "
        "handled monitoring in production?",
    ),
)

BY_ID: dict[str, Sentence] = {s.id: s for s in SENTENCES}

# Terms that are the whole reason this product needs a good engine: an engine
# that scores a respectable overall WER but misses every one of these is not
# usable for a technical interview. Scored separately in the report.
TECHNICAL_TERMS: tuple[str, ...] = (
    "rag",
    "architecture",
    "semantic",
    "search",
    "apis",
    "normalize",
    "security",
    "false",
    "positives",
    "vulnerability",
    "classification",
    "model",
    "deployed",
    "monitoring",
    "production",
)
