"""Prompt builders for Consulting Mode.

Same two-prompt split as Sales Mode (app/services/prompt_builder_sales.py),
tuned toward structured questions/recommendations and surfacing risks/
assumptions/decisions/dependencies, and with `engagement_context` folded into
the live ask flow so cross-session memory actually reaches the model.
"""

from __future__ import annotations

from typing import List

from app.schemas.consulting import ConsultingAskRequest, ConsultingSummaryRequest
from app.services.llm import LLMMessage

ASK_SYSTEM_PROMPT = """You are a real-time consulting engagement assistant. \
You are NOT the consultant speaking — you are advising the consultant who is \
live in a session with their client right now.

HOW TO ANSWER

The consultant is asking for help mid-session: a structured question to ask \
the client next, a recommendation, help spotting a risk/assumption/\
dependency, or general guidance on how to move the discussion forward.

- Speak TO the consultant, giving them something they can use immediately — \
a specific question to ask, a recommendation with brief reasoning, or a risk/\
assumption worth naming out loud.
- Ground guidance in the engagement context (client, project, prior session \
notes) and any uploaded background documents when relevant — use the \
information naturally without ever referring to "the documents" or "context" \
directly to the consultant.
- When prior-session context is available and the current discussion relates \
to it, connect the two explicitly ("Following up on the integration risk \
from last session...") — this is what makes the engagement feel continuous \
rather than each session starting from zero.
- If background is thin, give solid general consulting judgment for the \
situation rather than stalling.
- Keep it SHORT — this is read in real time during a live session: 1-4 \
sentences, or a short bulleted list of 2-3 options/questions when that fits \
better. Never write an essay.
- No preamble, no meta-commentary about being an AI assistant. Go straight to \
the substance.
"""

_STYLE_INSTRUCTIONS = {
    "natural": "Sound like an experienced, calm senior consultant.",
    "technical": "Lean into concrete technical/domain detail where it strengthens the point.",
    "concise": "Be maximally direct — the shortest usable guidance, no filler.",
}

_LENGTH_INSTRUCTIONS = {
    "brief": "Ceiling: 1-2 sentences or a 2-item bullet list.",
    "default": "Ceiling: roughly 40-90 words.",
    "detailed": "Ceiling: roughly 120 words — only use the extra room if the question genuinely needs it.",
}


def _context_blocks(request: ConsultingAskRequest) -> List[str]:
    blocks: List[str] = []
    if request.client_name:
        blocks.append(f"Client: {request.client_name}")
    if request.project_name:
        blocks.append(f"Project: {request.project_name}")
    if request.engagement_context:
        blocks.append(f"Engagement context (prior sessions):\n{request.engagement_context}")
    if request.retrieved_context:
        chunks = "\n\n".join(chunk.text for chunk in request.retrieved_context)
        blocks.append(f"Background documents:\n{chunks}")
    return blocks


def build_ask_messages(request: ConsultingAskRequest) -> List[LLMMessage]:
    messages: List[LLMMessage] = [LLMMessage("system", ASK_SYSTEM_PROMPT)]

    for turn in request.conversation_history:
        messages.append(LLMMessage("user", turn.question))
        messages.append(LLMMessage("assistant", turn.answer))

    parts: List[str] = []
    blocks = _context_blocks(request)
    if blocks:
        parts.append("CONTEXT:\n" + "\n\n".join(blocks))
    parts.append(f"The consultant asks:\n{request.question}")
    parts.append(
        f"{_LENGTH_INSTRUCTIONS[request.answer_length]} {_STYLE_INSTRUCTIONS[request.response_style]}\n"
        "Reply with only the guidance — no headers, no restating the question."
    )
    messages.append(LLMMessage("user", "\n\n---\n\n".join(parts)))
    return messages


SUMMARY_SYSTEM_PROMPT = """You are an expert management consultant producing \
structured session notes. Summarize a completed consulting session from its \
transcript and the items the consultant tracked live (risks, assumptions, \
decisions, dependencies, action items).

Be concrete and grounded only in what's in the transcript/tracked items — do \
not invent decisions, owners, or dates that weren't mentioned.

You must respond with valid JSON only, matching exactly the schema described \
in the user message. Do not include any text outside the JSON object."""


def build_summary_prompt(request: ConsultingSummaryRequest) -> tuple[str, str]:
    header = []
    if request.client_name:
        header.append(f"CLIENT\n{request.client_name}")
    if request.project_name:
        header.append(f"PROJECT\n{request.project_name}")
    header_block = "\n\n".join(header) if header else "(No client/project provided.)"

    transcript_block = (
        "\n".join(f"{turn.speaker}: {turn.text}" for turn in request.turns)
        or "(No transcript captured.)"
    )
    tracked_block = (
        f"Risks noted during the session:\n{_bullet_list(request.risks)}\n\n"
        f"Assumptions noted during the session:\n{_bullet_list(request.assumptions)}\n\n"
        f"Decisions made during the session:\n{_bullet_list(request.decisions)}\n\n"
        f"Dependencies noted during the session:\n{_bullet_list(request.dependencies)}\n\n"
        f"Action items noted during the session:\n{_bullet_list(request.action_items)}"
    )

    user_prompt = f"""{header_block}

SESSION TRANSCRIPT
{transcript_block}

TRACKED ITEMS
{tracked_block}

Respond with a single JSON object matching exactly this schema:
{{
  "summary": "string — 2-4 sentence overview of the session",
  "key_points": ["string", "..."],
  "risks": ["string", "..."],
  "assumptions": ["string", "..."],
  "decisions": ["string", "..."],
  "dependencies": ["string", "..."],
  "action_items": ["string", "..."],
  "open_questions": ["string", "..."]
}}"""

    return SUMMARY_SYSTEM_PROMPT, user_prompt


def _bullet_list(items: List[str]) -> str:
    if not items:
        return "(none noted)"
    return "\n".join(f"- {item}" for item in items)
