"""InterviewAnalysisPromptBuilder.

Builds the two prompt shapes the two-stage analysis pipeline needs:

1. `build_question_prompt` — one question + its answer + its own retrieved RAG
   context -> a `QuestionAnalysis`-shaped JSON response.
2. `build_overall_prompt` — all per-question analyses + role/company/JD ->
   an `OverallInterviewAnalysis`-shaped JSON response.

Neither prompt ever includes the full raw transcript or unrelated documents —
only the specific question/answer/context relevant to what's being analyzed
right now (spec sections 13, 25).
"""

from __future__ import annotations

from typing import List, Optional

from app.schemas.analysis import QuestionAnalysis
from app.schemas.interview import QuestionAnswer

SYSTEM_INSTRUCTIONS = """You are an expert technical interviewer and interview coach.

Analyze the candidate's completed interview using only the candidate context \
and retrieved knowledge provided.

Do not invent experience.

Do not attribute technologies, projects, employers, responsibilities, or \
achievements to the candidate unless supported by the supplied context.

Distinguish between:
- What the candidate actually said
- What is supported by their documents
- What is missing
- What could be improved

Evaluate answers based on technical correctness, practical depth, clarity, \
structure, relevance, and communication.

When suggesting an improved answer, preserve the candidate's actual \
experience and do not fabricate accomplishments.

If information needed to verify a claim is missing from the supplied context, \
say so explicitly using the phrase "Not established from the supplied \
candidate context." Do not guess.

If the candidate's answer contradicts the supplied candidate context (for \
example, claiming a technology or deployment method not found in their \
resume or project documents), flag this directly in your assessment rather \
than silently accepting or silently correcting it.

You must respond with valid JSON only, matching exactly the schema described \
in the user message. Do not include any text outside the JSON object."""

RUBRIC = """Score each dimension from 0-100 using this rubric:

Technical Knowledge (0-100): depth and correctness of technical explanation.
Communication (0-100): clarity, structure, and how well the answer would land in a real interview.
Practical Experience (0-100): concrete, specific, hands-on detail vs. generic/theoretical answers.
Clarity (0-100): how easy the answer is to follow.
Confidence (0-100): how directly and assuredly the candidate answered.

You must briefly explain the reasoning behind any score above 85 or below 40 \
in the relevant text field (assessment, or summary for overall scores). Avoid \
arbitrary scoring — every score should be traceable to something specific in \
the answer or context."""


def _format_retrieved_context(qa: QuestionAnswer) -> str:
    if not qa.retrieved_context:
        return "(No relevant context was retrieved from the candidate's documents for this question.)"
    lines = []
    for chunk in qa.retrieved_context:
        lines.append(
            f"[Source: {chunk.source_filename} ({chunk.document_type}), relevance {chunk.score:.2f}]\n{chunk.text}"
        )
    return "\n\n".join(lines)


def build_question_prompt(
    qa: QuestionAnswer,
    role: Optional[str],
    company: Optional[str],
    job_description: Optional[str],
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for Stage 1 (per-question analysis)."""

    context_header = []
    if role:
        context_header.append(f"ROLE\n{role}")
    if company:
        context_header.append(f"COMPANY\n{company}")
    if job_description:
        context_header.append(f"JOB DESCRIPTION\n{job_description}")
    header = "\n\n".join(context_header) if context_header else "(No role/company/job description provided.)"

    user_prompt = f"""{header}

RELEVANT RETRIEVED KNOWLEDGE
{_format_retrieved_context(qa)}

INTERVIEW QUESTION
{qa.question}

CANDIDATE ANSWER
{qa.candidate_answer or "(No answer was captured for this question.)"}

{RUBRIC}

Respond with a single JSON object matching exactly this schema:
{{
  "assessment": "string — what the candidate actually said, evaluated against the rubric, referencing the retrieved knowledge where relevant",
  "score": 0,
  "strengths": ["string", "..."],
  "issues": ["string", "..."],
  "improved_answer": "string — first-person, conversational, interview-ready, grounded only in the retrieved knowledge and the candidate's actual answer; do not fabricate accomplishments"
}}

The field "question_id" is not part of your response — it is added separately."""

    return SYSTEM_INSTRUCTIONS, user_prompt


def build_overall_prompt(
    question_analyses: List[QuestionAnalysis],
    role: Optional[str],
    company: Optional[str],
    job_description: Optional[str],
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for Stage 2 (aggregate overall
    analysis). Built from the already-structured per-question analyses, not
    the raw transcript again (spec section 25/26)."""

    context_header = []
    if role:
        context_header.append(f"ROLE\n{role}")
    if company:
        context_header.append(f"COMPANY\n{company}")
    if job_description:
        context_header.append(f"JOB DESCRIPTION\n{job_description}")
    header = "\n\n".join(context_header) if context_header else "(No role/company/job description provided.)"

    successful = [qa for qa in question_analyses if not qa.failed]
    questions_block = "\n\n".join(
        f"Q{i + 1}: {qa.question}\nScore: {qa.score}\nAssessment: {qa.assessment}\n"
        f"Strengths: {', '.join(qa.strengths) or '(none noted)'}\n"
        f"Issues: {', '.join(qa.issues) or '(none noted)'}"
        for i, qa in enumerate(successful)
    )
    if not questions_block:
        questions_block = "(No question-level analyses completed successfully.)"

    user_prompt = f"""{header}

PER-QUESTION ANALYSIS RESULTS
{questions_block}

{RUBRIC}

Based on the per-question analyses above, produce an overall assessment of \
the candidate's interview performance. Respond with a single JSON object \
matching exactly this schema:
{{
  "overall_score": 0,
  "technical_score": 0,
  "communication_score": 0,
  "practical_experience_score": 0,
  "confidence_score": 0,
  "summary": "string — 2-4 sentence overall summary",
  "strengths": ["string", "..."],
  "weaknesses": ["string", "..."],
  "recommendations": ["string", "..."]
}}"""

    return SYSTEM_INSTRUCTIONS, user_prompt
