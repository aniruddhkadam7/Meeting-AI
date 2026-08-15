"""Schemas for Consulting Mode.

Same two-shape split as Sales Mode (app/schemas/sales.py): a live single-
question "ask" flow during a client session, plus an end-of-session
structured-notes summary. The key difference from Sales is `engagement_context`
— a short rolling digest of prior sessions with the same client, carried by the
desktop app across the whole engagement, that gives cross-session memory to
the live ask flow.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MAX_QUESTION_LENGTH = 2_000
MAX_CHUNK_TEXT_LENGTH = 4_000
MAX_CHUNKS = 10
MAX_NAME_LENGTH = 300
MAX_HISTORY_TURNS = 20
MAX_HISTORY_TEXT_LENGTH = 4_000
MAX_ENGAGEMENT_CONTEXT_LENGTH = 8_000
MAX_TURNS_FOR_SUMMARY = 400
MAX_TRACKED_ITEMS = 100

AnswerLength = Literal["brief", "default", "detailed"]
ResponseStyle = Literal["natural", "technical", "concise"]


class ConsultingRetrievedChunk(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class ConsultingConversationTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class ConsultingAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_history: List[ConsultingConversationTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    retrieved_context: List[ConsultingRetrievedChunk] = Field(default_factory=list, max_length=MAX_CHUNKS)
    client_name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    project_name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    engagement_context: Optional[str] = Field(default=None, max_length=MAX_ENGAGEMENT_CONTEXT_LENGTH)
    answer_length: AnswerLength = "default"
    response_style: ResponseStyle = "natural"


class ConsultingAskResponse(BaseModel):
    answer: str
    latency_ms: float


class ConsultingTurnIn(BaseModel):
    speaker: Literal["CONSULTANT", "CLIENT"]
    text: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class ConsultingSummaryRequest(BaseModel):
    turns: List[ConsultingTurnIn] = Field(default_factory=list, max_length=MAX_TURNS_FOR_SUMMARY)
    risks: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    assumptions: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    decisions: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    dependencies: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    action_items: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    client_name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    project_name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)


class ConsultingNote(BaseModel):
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    message: str = ""
