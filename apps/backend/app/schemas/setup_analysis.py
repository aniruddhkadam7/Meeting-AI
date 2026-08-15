"""Schemas for the New Interview setup page's auto-analysis endpoint.

Lightweight and separate from `app/schemas/ask.py` and `app/schemas/
interview.py`: this endpoint only ever extracts a short structured summary
from whatever CV/JD text is pasted or uploaded as plain text on the setup
page, before an interview session exists. It never scores or judges
anything.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

MAX_RESUME_TEXT_LENGTH = 20_000
MAX_JOB_DESCRIPTION_TEXT_LENGTH = 10_000
MAX_LIST_ITEMS = 12


class SetupAnalysisRequest(BaseModel):
    resume_text: Optional[str] = Field(default=None, max_length=MAX_RESUME_TEXT_LENGTH)
    job_description_text: Optional[str] = Field(default=None, max_length=MAX_JOB_DESCRIPTION_TEXT_LENGTH)


class SetupAnalysisResponse(BaseModel):
    job_title: Optional[str] = None
    company: Optional[str] = None
    seniority: Optional[str] = None
    employment_type: Optional[str] = None
    key_responsibilities: List[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    required_skills: List[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    technologies: List[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    focus_areas: List[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    candidate_highlights: List[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
