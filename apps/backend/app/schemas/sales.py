"""Schemas for Sales Mode.

Two shapes, mirroring the Interview Mode / analysis split:

1. `SalesAskRequest`/`SalesAskResponse` — the live single-question "suggest a
   response" flow during a call. Same minimal shape as `app/schemas/ask.py`,
   plus sales-specific context (customer/company, deal stage) that shifts the
   system prompt's tone rather than gating anything.
2. `SalesSummaryRequest`/`SalesCallSummary` — the end-of-call structured
   summary, built from the full turn list plus whatever requirements/
   objections/commitments were tracked live during the call.
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
CallStage = Literal["discovery", "demo", "negotiation", "closing", "other"]


class SalesRetrievedChunk(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class SalesConversationTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class SalesAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_history: List[SalesConversationTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    retrieved_context: List[SalesRetrievedChunk] = Field(default_factory=list, max_length=MAX_CHUNKS)
    customer_name: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    company_name: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    call_stage: CallStage = "discovery"
    answer_length: AnswerLength = "default"
    response_style: ResponseStyle = "natural"


class SalesAskResponse(BaseModel):
    answer: str
    latency_ms: float


class SalesTurnIn(BaseModel):
    speaker: Literal["REP", "CUSTOMER"]
    text: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class SalesSummaryRequest(BaseModel):
    turns: List[SalesTurnIn] = Field(default_factory=list, max_length=MAX_TURNS_FOR_SUMMARY)
    requirements: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    objections: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    commitments: List[str] = Field(default_factory=list, max_length=MAX_TRACKED_ITEMS)
    customer_name: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    company_name: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)


class SalesCallSummary(BaseModel):
    summary: str = ""
    key_requirements: List[str] = Field(default_factory=list)
    key_objections: List[str] = Field(default_factory=list)
    commitments: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    buying_intent: str = Field(default="unknown", description="One of: low, medium, high, unknown")
    message: str = ""
