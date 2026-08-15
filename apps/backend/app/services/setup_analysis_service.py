"""Auto-analysis for the New Interview setup page.

Deliberately minimal, following the same "one call, no extra round trips"
shape as `app/services/ask_service.py`: whatever CV/JD text the user has
pasted or uploaded (as plain text) gets summarized in a single LLM call into
a short structured "Interview Focus" the setup page can display. Never
blocks Start Interview — the desktop app calls this in the background while
the user keeps typing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from app.core.config import Settings, get_settings
from app.schemas.setup_analysis import SetupAnalysisRequest, SetupAnalysisResponse
from app.services.llm import LLMMessage, get_llm_provider

logger = logging.getLogger("app.setup_analysis")

_EMPTY_RESPONSE = SetupAnalysisResponse()

SYSTEM_PROMPT = """You extract a thorough, structured summary from a \
candidate's resume and/or a job description, for an interview-prep tool. You \
are not writing anything for the interview itself — only summarizing what \
was given, but you should be THOROUGH: pull out every distinct \
responsibility, skill, technology, and qualification actually stated in the \
text, not just the first few. Read the whole document before answering.

Respond with ONLY a single JSON object, no prose before or after, matching \
exactly this shape:

{
  "job_title": string or null,
  "company": string or null,
  "seniority": string or null (e.g. "Junior", "Mid-level", "Senior", \
"Lead/Staff" — inferred from years-of-experience requirements, title, or \
scope of responsibility if stated),
  "employment_type": string or null (e.g. "Full-time", "Contract", \
"Remote", "Hybrid" — only if the text actually says so),
  "key_responsibilities": string[] (up to 12, one item per distinct duty or \
responsibility actually listed — do not merge multiple duties into one item, \
do not stop at 3-4 if more are stated),
  "required_skills": string[] (up to 12, every distinct skill or \
qualification named, including soft skills and years-of-experience \
requirements if stated as their own bullet),
  "technologies": string[] (up to 12, every specific tool, language, \
framework, platform, or product name mentioned — list names only, no \
descriptions),
  "focus_areas": string[] (up to 8, short phrases describing what an \
interviewer for this role would likely probe, derived from the \
responsibilities and requirements above),
  "candidate_highlights": string[] (up to 10, short phrases about the \
candidate's own relevant experience/projects/achievements from the resume — \
omit entirely if no resume text was given)
}

Only use information actually present in the text given to you — extract \
comprehensively, but never invent employers, titles, metrics, or \
requirements that are not in the text. If only a resume is given, leave \
job_title/company/seniority/employment_type/required_skills/focus_areas \
empty or null unless they are inferable from the resume itself. If only a \
job description is given, leave candidate_highlights as an empty list."""


def _build_user_prompt(request: SetupAnalysisRequest) -> str:
    parts: List[str] = []
    if request.resume_text and request.resume_text.strip():
        parts.append(f"RESUME:\n{request.resume_text.strip()}")
    if request.job_description_text and request.job_description_text.strip():
        parts.append(f"JOB DESCRIPTION:\n{request.job_description_text.strip()}")
    parts.append("Return the JSON object now.")
    return "\n\n---\n\n".join(parts)


def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction — models occasionally wrap the object in a
    code fence despite instructions not to; strip that before parsing rather
    than failing the whole request over formatting."""
    stripped = text.strip()
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        stripped = match.group(0)
    return json.loads(stripped)


class SetupAnalysisService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Same fast/cheap model as Interview Mode's live answers — this is a
        # short, low-stakes extraction, not deep analysis.
        self._provider = get_llm_provider(self._settings, model=self._settings.ask_model)

    async def analyze(self, request: SetupAnalysisRequest) -> SetupAnalysisResponse:
        has_resume = bool(request.resume_text and request.resume_text.strip())
        has_jd = bool(request.job_description_text and request.job_description_text.strip())
        if not has_resume and not has_jd:
            return SetupAnalysisResponse()

        messages = [
            LLMMessage("system", SYSTEM_PROMPT),
            LLMMessage("user", _build_user_prompt(request)),
        ]

        try:
            raw = await self._provider.generate(messages, temperature=0.1, max_tokens=1100)
            data = _extract_json(raw)
            return SetupAnalysisResponse(**data)
        except Exception:
            logger.exception("[SETUP] failed to analyze setup context, returning empty summary")
            return SetupAnalysisResponse()


def get_setup_analysis_service() -> SetupAnalysisService:
    return SetupAnalysisService()
