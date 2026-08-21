"""Schemas for Meeting Mode.

Two shapes, mirroring the Interview Mode / analysis split (and Sales Mode's
own schema split, `app/schemas/sales.py`):

1. `MeetingAskRequest`/`MeetingAskResponse` — the live single-question
   "quick answer / talking point" flow during a meeting. Same minimal shape
   as `app/schemas/ask.py`, plus meeting-specific context (title,
   participants) that shifts the system prompt's tone rather than gating
   anything.
2. `MeetingSummaryRequest`/`MeetingSummary` — the end-of-meeting structured
   summary, built from the full turn list plus whatever key points/decisions/
   action items were tracked live during the meeting.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MAX_QUESTION_LENGTH = 2_000
MAX_CHUNK_TEXT_LENGTH = 4_000
MAX_CHUNKS = 10
MAX_ROLE_LENGTH = 300
MAX_HISTORY_TURNS = 20
MAX_HISTORY_TEXT_LENGTH = 4_000
MAX_TURNS_FOR_SUMMARY = 400
MAX_TRACKED_ITEMS = 100
MAX_ITEM_TEXT_LENGTH = 1_000

AnswerLength = Literal["brief", "default", "detailed"]
ResponseStyle = Literal["natural", "technical", "concise"]
Humanization = Literal["natural", "conversational", "formal"]
# Only providers with a real LLMProvider implementation — see
# app/schemas/ask.py's LlmProviderChoice for the full rationale.
LlmProviderChoice = Literal["openai", "anthropic", "gemini"]


class MeetingRetrievedChunk(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class MeetingConversationTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class MeetingAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_history: List[MeetingConversationTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    retrieved_context: List[MeetingRetrievedChunk] = Field(default_factory=list, max_length=MAX_CHUNKS)
    meeting_title: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    participants: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    answer_length: AnswerLength = "default"
    response_style: ResponseStyle = "natural"
    humanization: Humanization = "natural"
    # None keeps the server-configured LLM_PROVIDER default — see
    # app/schemas/ask.py's AskRequest.llm_provider for the full rationale.
    llm_provider: Optional[LlmProviderChoice] = None


class MeetingAskResponse(BaseModel):
    answer: str
    latency_ms: float


class MeetingTurnIn(BaseModel):
    speaker: Literal["ME", "OTHER"]
    text: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class MeetingSummaryRequest(BaseModel):
    turns: List[MeetingTurnIn] = Field(default_factory=list, max_length=MAX_TURNS_FOR_SUMMARY)
    key_points: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    decisions: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    action_items: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    meeting_title: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    participants: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)


class MeetingSummary(BaseModel):
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    message: str = ""
