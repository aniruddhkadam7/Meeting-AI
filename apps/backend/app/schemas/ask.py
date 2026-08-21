"""Schemas for the lightweight live-interview "ask" endpoint (Interview Mode).

Deliberately much smaller than the full interview-analysis schema
(app/schemas/interview.py) — this carries the current question, the running
Interview Mode conversation so follow-ups resolve, whatever context happens to
be available, and the user's answer length/style preferences. No transcript,
no scoring rubric.

Every context field is optional and every one of them is *additive*: the
answer is produced by the model regardless of whether any of them are
present. Retrieval personalizes the answer, it never gates it — see
app/services/ask_service.py.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MAX_QUESTION_LENGTH = 2_000
MAX_CHUNK_TEXT_LENGTH = 4_000
MAX_CHUNKS = 10
MAX_CANDIDATE_CONTEXT_LENGTH = 20_000
MAX_ROLE_LENGTH = 300
MAX_JOB_DESCRIPTION_LENGTH = 10_000

# Prior turns of the current Interview Mode session, oldest first. Capped
# rather than unbounded: a long interview would otherwise grow the prompt (and
# therefore cost and time-to-first-token) without limit, and the caller already
# sends only the most recent turns. The cap is a backstop, not the policy.
MAX_HISTORY_TURNS = 20
MAX_HISTORY_TEXT_LENGTH = 4_000

AnswerLength = Literal["brief", "default", "detailed"]
ResponseStyle = Literal["natural", "technical", "concise"]
EnglishLevel = Literal["simple", "professional", "advanced"]
Humanization = Literal["natural", "conversational", "formal"]
# Only providers with a real LLMProvider implementation (see
# app/services/llm/__init__.py::get_llm_provider) — DeepSeek isn't built yet,
# so it's not a valid value here even though the desktop app's header
# dropdown lists it (disabled) for a future provider.
LlmProviderChoice = Literal["openai", "anthropic", "gemini"]


class AskRetrievedChunk(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class ConversationTurn(BaseModel):
    """One completed exchange earlier in this Interview Mode session.

    Sent so follow-up questions resolve: "Why did you choose that?" only means
    anything relative to what was already discussed.
    """

    question: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    # Oldest first, excluding the current question. Optional — the first
    # question of a session sends none and behaves exactly as before.
    conversation_history: List[ConversationTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    retrieved_context: List[AskRetrievedChunk] = Field(default_factory=list, max_length=MAX_CHUNKS)
    candidate_context: Optional[str] = Field(default=None, max_length=MAX_CANDIDATE_CONTEXT_LENGTH)
    role: Optional[str] = Field(default=None, max_length=MAX_ROLE_LENGTH)
    job_description: Optional[str] = Field(default=None, max_length=MAX_JOB_DESCRIPTION_LENGTH)
    answer_length: AnswerLength = "default"
    response_style: ResponseStyle = "natural"
    english_level: EnglishLevel = "simple"
    humanization: Humanization = "natural"
    # None keeps the server-configured LLM_PROVIDER default (see
    # get_llm_provider) — set only when the user has explicitly chosen a
    # provider in the desktop app's header dropdown.
    llm_provider: Optional[LlmProviderChoice] = None


class AskResponse(BaseModel):
    answer: str
    latency_ms: float
