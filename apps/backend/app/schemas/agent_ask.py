"""Schemas for Custom Agents' live "ask" endpoint.

One generic request/response shape shared by every agent — predefined-role
or fully custom — instead of a new schema per role (that would recreate the
per-mode duplication `apps/backend/app/schemas/{ask,sales,consulting}.py`
already have). Mirrors `app/schemas/ask.py`'s `AskRequest` (question,
conversation history, retrieved context, answer-length/style knobs), plus
the fields needed to compose an agent's system prompt on the fly: which
predefined role (if any) it's based on, its optional description/custom
instructions, and the wider Personalization axes the Custom Agents spec adds
(answer_format, live_assistance — the latter is accepted here for schema
completeness/logging only; it does not change how a single ask is answered,
since "auto-send" behavior lives client-side).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MAX_QUESTION_LENGTH = 2_000
MAX_CHUNK_TEXT_LENGTH = 4_000
MAX_CHUNKS = 10
MAX_HISTORY_TURNS = 20
MAX_HISTORY_TEXT_LENGTH = 4_000
MAX_DESCRIPTION_LENGTH = 2_000
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 4_000
MAX_AGENT_NAME_LENGTH = 200

# Matches apps/desktop/src-tauri/src/agents' PredefinedRole enum values.
PredefinedRole = Literal[
    "SALESPERSON",
    "SALES_ENGINEER",
    "CONSULTANT",
    "RECRUITER",
    "CUSTOMER_SUPPORT",
    "PROJECT_MANAGER",
    "BUSINESS_ANALYST",
    "TECHNICAL_SUPPORT",
]

AnswerLength = Literal["concise", "balanced", "detailed", "adaptive"]
ResponseStyle = Literal["natural", "professional", "friendly", "technical"]
AnswerFormat = Literal["adaptive", "paragraph", "bullets", "step_by_step"]
LiveAssistance = Literal["manual", "suggest", "auto"]


class AgentPersonalization(BaseModel):
    answer_length: AnswerLength = "adaptive"
    response_style: ResponseStyle = "natural"
    answer_format: AnswerFormat = "adaptive"
    live_assistance: LiveAssistance = "manual"


class AgentRetrievedChunk(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class AgentConversationTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class AgentAskRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    agent_name: str = Field(..., min_length=1, max_length=MAX_AGENT_NAME_LENGTH)
    base_role: Optional[PredefinedRole] = None
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    custom_instructions: Optional[str] = Field(default=None, max_length=MAX_CUSTOM_INSTRUCTIONS_LENGTH)
    personalization: AgentPersonalization = Field(default_factory=AgentPersonalization)

    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_history: List[AgentConversationTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    retrieved_context: List[AgentRetrievedChunk] = Field(default_factory=list, max_length=MAX_CHUNKS)


class AgentAskResponse(BaseModel):
    answer: str
    latency_ms: float
