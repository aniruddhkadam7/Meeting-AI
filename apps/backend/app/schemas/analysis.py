"""Structured interview-analysis output schemas.

Two-stage shape (spec section 26):

    Stage 1 (per question): QuestionAnalysis
    Stage 2 (aggregate):    OverallInterviewAnalysis

All scores are explicitly AI-generated estimates, never objective measurements
— `OverallInterviewAnalysis.disclaimer` states this, and nothing in this schema
or the services that populate it should be read as ground truth. When the LLM
provider is `MockLLMProvider` (no API key configured / real provider
unavailable), every score is 0 and every list is empty, mirroring the Step 8
mock-analysis behavior this replaces — never let a mock path produce non-zero
scores that could be mistaken for a real assessment.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AnalysisStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # one or more question analyses failed but the
    # overall analysis still completed with the rest — see spec section 30.


class RetrievedSourceRef(BaseModel):
    filename: str
    document_type: str
    score: float
    text: str


class QuestionAnalysis(BaseModel):
    question_id: str
    question: str
    candidate_answer: str
    assessment: str = Field(
        ..., description="What the candidate actually said, evaluated against the rubric."
    )
    score: int = Field(ge=0, le=100)
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    improved_answer: str = Field(
        default="", description="Interview-ready rewrite grounded only in verified candidate context."
    )
    retrieved_sources: List[RetrievedSourceRef] = Field(default_factory=list)
    failed: bool = Field(
        default=False,
        description="True if this question's LLM analysis call failed — the rest of the interview's analysis still proceeds (spec section 30).",
    )
    error_message: Optional[str] = None


class OverallInterviewAnalysis(BaseModel):
    session_id: str
    status: AnalysisStatus

    overall_score: int = Field(ge=0, le=100)
    technical_score: int = Field(ge=0, le=100)
    communication_score: int = Field(ge=0, le=100)
    practical_experience_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)

    summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)

    questions: List[QuestionAnalysis] = Field(default_factory=list)

    disclaimer: str = (
        "These scores and this feedback are AI-generated estimates based only on "
        "the transcript and documents you provided. They are not an objective "
        "measurement of your skills or interview performance."
    )
    message: str = ""


# Kept for compatibility with anything still constructing the old flat shape
# (e.g. the mock-only response before question-level analysis exists).
AnalysisResponse = OverallInterviewAnalysis
