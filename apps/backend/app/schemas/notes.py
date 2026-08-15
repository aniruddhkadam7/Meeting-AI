"""Schemas for Notes Mode.

No live-call flow here (Notes has no overlay/turn concept) — just two
stateless text operations: summarizing a note's body, and answering a
question using one or more notes as optional context. Both reuse the same
"context personalizes, never gates" convention as the other modes.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

MAX_NOTE_BODY_LENGTH = 40_000
MAX_QUESTION_LENGTH = 2_000
MAX_NOTES_FOR_CONTEXT = 20
MAX_NOTE_TITLE_LENGTH = 300


class NotesSummaryRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=MAX_NOTE_TITLE_LENGTH)
    body: str = Field(..., min_length=1, max_length=MAX_NOTE_BODY_LENGTH)


class NoteSummary(BaseModel):
    summary: str = ""
    tasks: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    message: str = ""


class NoteContext(BaseModel):
    title: Optional[str] = Field(default=None, max_length=MAX_NOTE_TITLE_LENGTH)
    body: str = Field(..., min_length=1, max_length=MAX_NOTE_BODY_LENGTH)


class NotesAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    notes: List[NoteContext] = Field(default_factory=list, max_length=MAX_NOTES_FOR_CONTEXT)


class NotesAskResponse(BaseModel):
    answer: str
    latency_ms: float
