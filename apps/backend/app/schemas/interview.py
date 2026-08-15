"""Request schemas for the interview-analysis API.

These validate the shape of data the desktop app sends after the user explicitly
clicks "Analyze Interview". No audio, no raw documents, no embeddings, and no
vector database ever appear in this shape:

- `TranscriptSegment.text` is already-transcribed text produced entirely
  locally by the desktop's PocketSphinx pipeline (Step 4).
- `QuestionAnswer` pairs are extracted from the transcript entirely locally,
  deterministically, with no LLM call (Step 10 — `InterviewAnalyzer` on the
  desktop side, mirrored here only as the wire shape the backend validates).
- `RetrievedChunk` entries are the *already-retrieved* minimum text needed for
  each question, produced by a local RAG search
  (`packages/rag`) against the user's own documents — never the original
  documents, never raw embeddings, never the vector database itself.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

_TIMESTAMP_RE = re.compile(r"^(\d{2}:)?\d{2}:\d{2}$")

MAX_SEGMENT_TEXT_LENGTH = 10_000
MAX_SEGMENTS = 5_000
MAX_TRANSCRIPT_DURATION_SECONDS = 24 * 60 * 60  # 1 day, generous upper bound
MAX_RESUME_LENGTH = 50_000
MAX_JOB_DESCRIPTION_LENGTH = 20_000
MAX_PROJECT_NAME_LENGTH = 500
MAX_PROJECTS = 100
MAX_QUESTION_ANSWERS = 200
MAX_QUESTION_LENGTH = 2_000
MAX_ANSWER_LENGTH = 20_000
MAX_CHUNK_TEXT_LENGTH = 4_000
MAX_CHUNKS_PER_QUESTION = 20


class TranscriptSource(str, Enum):
    SYSTEM_AUDIO = "SYSTEM_AUDIO"
    MICROPHONE = "MICROPHONE"


class TranscriptSegment(BaseModel):
    timestamp: str = Field(
        ..., description="Relative timestamp, MM:SS or HH:MM:SS", examples=["00:00:04"]
    )
    source: TranscriptSource
    text: str = Field(..., min_length=1, max_length=MAX_SEGMENT_TEXT_LENGTH)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_format(cls, value: str) -> str:
        if not _TIMESTAMP_RE.match(value):
            raise ValueError("timestamp must be in MM:SS or HH:MM:SS format")
        return value

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("segment text must not be blank")
        return value


class Transcript(BaseModel):
    duration_seconds: int = Field(..., ge=0, le=MAX_TRANSCRIPT_DURATION_SECONDS)
    segments: List[TranscriptSegment] = Field(default_factory=list, max_length=MAX_SEGMENTS)


class CandidateContext(BaseModel):
    resume: Optional[str] = Field(default=None, max_length=MAX_RESUME_LENGTH)
    projects: List[str] = Field(default_factory=list, max_length=MAX_PROJECTS)

    @field_validator("projects")
    @classmethod
    def validate_project_names(cls, value: List[str]) -> List[str]:
        for project in value:
            if len(project) > MAX_PROJECT_NAME_LENGTH:
                raise ValueError(
                    f"project name exceeds {MAX_PROJECT_NAME_LENGTH} characters"
                )
        return value


class RetrievedChunk(BaseModel):
    """The minimum text needed from one locally-retrieved RAG chunk — never
    the source document, never an embedding vector."""

    text: str = Field(..., min_length=1, max_length=MAX_CHUNK_TEXT_LENGTH)
    source_filename: str = Field(..., min_length=1, max_length=300)
    document_type: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=1.0)


class QuestionAnswer(BaseModel):
    """One interviewer question paired with the candidate's answer, extracted
    locally on the desktop from the finalized transcript (deterministic
    turn-boundary heuristics — no LLM involved in this extraction step), plus
    the relevant chunks a local RAG search found for that specific question.
    """

    question_id: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    candidate_answer: str = Field(default="", max_length=MAX_ANSWER_LENGTH)
    timestamp: str = Field(..., examples=["00:12:32"])
    retrieved_context: List[RetrievedChunk] = Field(
        default_factory=list, max_length=MAX_CHUNKS_PER_QUESTION
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_format(cls, value: str) -> str:
        if not _TIMESTAMP_RE.match(value):
            raise ValueError("timestamp must be in MM:SS or HH:MM:SS format")
        return value


class InterviewAnalysisRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    role: Optional[str] = Field(default=None, max_length=300)
    company: Optional[str] = Field(default=None, max_length=300)
    job_description: Optional[str] = Field(default=None, max_length=MAX_JOB_DESCRIPTION_LENGTH)
    candidate_context: Optional[CandidateContext] = None

    # Kept for backward compatibility / non-QA-based callers (e.g. tests that
    # just want a duration/segment count) and so the mock provider and health
    # checks still have something to log — but real LLM analysis operates on
    # `question_answers`, not this raw transcript, per spec section 25 (avoid
    # stuffing an entire interview transcript into one prompt).
    transcript: Transcript

    question_answers: List[QuestionAnswer] = Field(
        default_factory=list, max_length=MAX_QUESTION_ANSWERS
    )

    @field_validator("transcript")
    @classmethod
    def validate_transcript_present(cls, value: Transcript) -> Transcript:
        if value is None:
            raise ValueError("transcript is required")
        return value
