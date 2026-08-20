"""Prompt builders for Meeting Mode.

Two prompts:

1. `build_ask_messages` — the live single-question flow: the user asks for
   help ("what did we agree on pricing?", "give me a quick recap of that
   point") mid-meeting, and gets one quick answer or talking point.
   Optimized for the same latency constraint as Interview Mode's ask flow
   (see app/services/ask_service.py) — one LLM call, no extra round trips.
2. `build_summary_prompt` — end-of-meeting structured summary from the full
   turn list plus whatever key points/decisions/action items were tracked
   live.
"""

from __future__ import annotations

from typing import List

from app.schemas.meeting import MeetingAskRequest, MeetingSummaryRequest
from app.services.llm import LLMMessage

ASK_SYSTEM_PROMPT = """You are a real-time meeting assistant. You are NOT a \
participant speaking in the meeting — you are a quiet aide the user \
consults silently while the meeting is happening live.

HOW TO ANSWER

The user is asking you for help with something that just came up in the \
meeting — a quick recap of a point, a clarifying answer, a fact from the \
reference material, or a suggestion for what to say or ask next. Give them \
something they can use or say immediately, not a lecture.

- Speak TO the user, giving them the information or wording they can use \
right now.
- Ground answers in whatever meeting title/participants context is given, \
and in the agenda/reference documents when relevant — but never mention \
"the documents" or "retrieved context" to the user; just use the \
information naturally, as if you already knew it.
- If the user asks a factual question and the background context has the \
answer, give the answer directly and concisely — no hedging, no "based on \
the provided information".
- If background is thin or absent, give solid general guidance for the \
situation instead of stalling or asking for more information — the user is \
in a live meeting and needs something usable immediately.
- Keep it SHORT. This is being read in real time during a live meeting: 1-4 \
sentences, or a short bulleted list of 2-3 points when the question calls \
for options. Never write an essay.
- No preamble ("Great question!"), no meta-commentary about being an AI \
assistant. Go straight to the answer.
- Plain, natural language. Markdown bullets are fine for multiple points; \
otherwise plain sentences.
"""

_STYLE_INSTRUCTIONS = {
    "natural": "Sound like a calm, well-prepared colleague.",
    "technical": "Lean into concrete technical/factual detail where it strengthens the point.",
    "concise": "Be maximally direct — the shortest usable answer, no filler.",
}

_LENGTH_INSTRUCTIONS = {
    "brief": "Ceiling: 1-2 sentences or a 2-item bullet list.",
    "default": "Ceiling: roughly 40-90 words.",
    "detailed": "Ceiling: roughly 120 words — only use the extra room if the question genuinely needs it.",
}


def _context_blocks(request: MeetingAskRequest) -> List[str]:
    blocks: List[str] = []
    if request.meeting_title:
        blocks.append(f"Meeting: {request.meeting_title}")
    if request.participants:
        blocks.append(f"Participants: {request.participants}")
    if request.retrieved_context:
        chunks = "\n\n".join(chunk.text for chunk in request.retrieved_context)
        blocks.append(f"Agenda/reference background:\n{chunks}")
    return blocks


def build_ask_messages(request: MeetingAskRequest) -> List[LLMMessage]:
    messages: List[LLMMessage] = [LLMMessage("system", ASK_SYSTEM_PROMPT)]

    for turn in request.conversation_history:
        messages.append(LLMMessage("user", turn.question))
        messages.append(LLMMessage("assistant", turn.answer))

    parts: List[str] = []
    blocks = _context_blocks(request)
    if blocks:
        parts.append("CONTEXT:\n" + "\n\n".join(blocks))
    parts.append(f"The user asks:\n{request.question}")
    parts.append(
        f"{_LENGTH_INSTRUCTIONS[request.answer_length]} {_STYLE_INSTRUCTIONS[request.response_style]}\n"
        "Reply with only the answer — no headers, no restating the question."
    )
    messages.append(LLMMessage("user", "\n\n---\n\n".join(parts)))
    return messages


SUMMARY_SYSTEM_PROMPT = """You are an expert meeting notes analyst. \
Summarize a completed meeting from its transcript and the items the user \
tracked live during the meeting (key points, decisions, action items).

Be concrete and grounded only in what's in the transcript/tracked items — do \
not invent decisions, owners, or deadlines that weren't mentioned.

You must respond with valid JSON only, matching exactly the schema described \
in the user message. Do not include any text outside the JSON object."""


def build_summary_prompt(request: MeetingSummaryRequest) -> tuple[str, str]:
    header = []
    if request.meeting_title:
        header.append(f"MEETING\n{request.meeting_title}")
    if request.participants:
        header.append(f"PARTICIPANTS\n{request.participants}")
    header_block = "\n\n".join(header) if header else "(No meeting title/participants provided.)"

    transcript_block = (
        "\n".join(f"{turn.speaker}: {turn.text}" for turn in request.turns)
        or "(No transcript captured.)"
    )
    tracked_block = (
        f"Key points noted during the meeting:\n{_bullet_list(request.key_points)}\n\n"
        f"Decisions made during the meeting:\n{_bullet_list(request.decisions)}\n\n"
        f"Action items raised during the meeting:\n{_bullet_list(request.action_items)}"
    )

    user_prompt = f"""{header_block}

MEETING TRANSCRIPT
{transcript_block}

TRACKED ITEMS
{tracked_block}

Respond with a single JSON object matching exactly this schema:
{{
  "summary": "string — 2-4 sentence overview of the meeting",
  "key_points": ["string", "..."],
  "decisions": ["string", "..."],
  "action_items": ["string", "..."],
  "next_steps": ["string", "..."]
}}"""

    return SUMMARY_SYSTEM_PROMPT, user_prompt


def _bullet_list(items: List[str]) -> str:
    if not items:
        return "(none noted)"
    return "\n".join(f"- {item}" for item in items)
