"""Prompt builders for Sales Mode.

Two prompts:

1. `build_ask_messages` — the live single-question flow: the rep asks for
   help ("how do I respond to this price objection?") mid-call, and gets one
   suggested response/talking point. Optimized for the same latency
   constraint as Interview Mode's ask flow (see app/services/ask_service.py)
   — one LLM call, no extra round trips.
2. `build_summary_prompt` — end-of-call structured summary from the full turn
   list plus whatever requirements/objections/commitments were tracked live.
"""

from __future__ import annotations

from typing import List

from app.schemas.sales import SalesAskRequest, SalesSummaryRequest
from app.services.llm import LLMMessage

ASK_SYSTEM_PROMPT = """You are a real-time sales call assistant. You are NOT \
the salesperson speaking — you are a coach whispering suggestions to the \
sales rep who is live on a call with a customer right now.

HOW TO ANSWER

The rep is asking you for help handling something that just came up on the \
call — an objection, a question they don't know how to answer, a request for \
a talking point, or general guidance on how to move the conversation forward. \
Give them something they can say or do immediately, not a lecture about sales \
technique.

- Speak TO the rep, giving them words or a strategy they can use right now — \
e.g. "Acknowledge the price concern, then pivot to the ROI angle: ..." or a \
suggested line they could say directly to the customer.
- Ground suggestions in whatever customer/company/deal-stage context is \
given, and in the product/pricing background documents when relevant — but \
never mention "the documents" or "retrieved context" to the rep; just use the \
information naturally, as if you already knew it.
- If the rep asks a factual question about the product/pricing/customer and \
the background context has the answer, give the answer directly and \
concisely — no hedging, no "based on the provided information".
- If background is thin or absent, give solid general sales guidance for the \
situation instead of stalling or asking for more information — the rep is on \
a live call and needs something usable immediately.
- Keep it SHORT. This is being read in real time during a live call: 1-4 \
sentences, or a short bulleted list of 2-3 talking points when the question \
calls for options. Never write an essay.
- No preamble ("Great question!"), no meta-commentary about being an AI \
assistant. Go straight to the suggestion.
- Plain, natural language. Markdown bullets are fine for multiple options; \
otherwise plain sentences.
"""

_STYLE_INSTRUCTIONS = {
    "natural": "Sound like an experienced, calm sales coach.",
    "technical": "Lean into concrete product/technical detail where it strengthens the point.",
    "concise": "Be maximally direct — the shortest usable suggestion, no filler.",
}

_LENGTH_INSTRUCTIONS = {
    "brief": "Ceiling: 1-2 sentences or a 2-item bullet list.",
    "default": "Ceiling: roughly 40-90 words.",
    "detailed": "Ceiling: roughly 120 words — only use the extra room if the question genuinely needs it.",
}


def _context_blocks(request: SalesAskRequest) -> List[str]:
    blocks: List[str] = []
    if request.customer_name:
        blocks.append(f"Customer: {request.customer_name}")
    if request.company_name:
        blocks.append(f"Company: {request.company_name}")
    blocks.append(f"Call stage: {request.call_stage}")
    if request.retrieved_context:
        chunks = "\n\n".join(chunk.text for chunk in request.retrieved_context)
        blocks.append(f"Product/pricing background:\n{chunks}")
    return blocks


def build_ask_messages(request: SalesAskRequest) -> List[LLMMessage]:
    messages: List[LLMMessage] = [LLMMessage("system", ASK_SYSTEM_PROMPT)]

    for turn in request.conversation_history:
        messages.append(LLMMessage("user", turn.question))
        messages.append(LLMMessage("assistant", turn.answer))

    parts: List[str] = []
    blocks = _context_blocks(request)
    if blocks:
        parts.append("CONTEXT:\n" + "\n\n".join(blocks))
    parts.append(f"The rep asks:\n{request.question}")
    parts.append(
        f"{_LENGTH_INSTRUCTIONS[request.answer_length]} {_STYLE_INSTRUCTIONS[request.response_style]}\n"
        "Reply with only the suggestion — no headers, no restating the question."
    )
    messages.append(LLMMessage("user", "\n\n---\n\n".join(parts)))
    return messages


SUMMARY_SYSTEM_PROMPT = """You are an expert sales operations analyst. \
Summarize a completed sales call from its transcript and the items the rep \
tracked live during the call (requirements, objections, commitments).

Be concrete and grounded only in what's in the transcript/tracked items — do \
not invent commitments, prices, or timelines that weren't mentioned.

You must respond with valid JSON only, matching exactly the schema described \
in the user message. Do not include any text outside the JSON object."""


def build_summary_prompt(request: SalesSummaryRequest) -> tuple[str, str]:
    header = []
    if request.customer_name:
        header.append(f"CUSTOMER\n{request.customer_name}")
    if request.company_name:
        header.append(f"COMPANY\n{request.company_name}")
    header_block = "\n\n".join(header) if header else "(No customer/company provided.)"

    transcript_block = (
        "\n".join(f"{turn.speaker}: {turn.text}" for turn in request.turns)
        or "(No transcript captured.)"
    )
    tracked_block = (
        f"Requirements noted during the call:\n{_bullet_list(request.requirements)}\n\n"
        f"Objections raised during the call:\n{_bullet_list(request.objections)}\n\n"
        f"Commitments made during the call:\n{_bullet_list(request.commitments)}"
    )

    user_prompt = f"""{header_block}

CALL TRANSCRIPT
{transcript_block}

TRACKED ITEMS
{tracked_block}

Respond with a single JSON object matching exactly this schema:
{{
  "summary": "string — 2-4 sentence overview of the call",
  "key_requirements": ["string", "..."],
  "key_objections": ["string", "..."],
  "commitments": ["string", "..."],
  "action_items": ["string", "..."],
  "next_steps": ["string", "..."],
  "buying_intent": "one of: low, medium, high, unknown"
}}"""

    return SUMMARY_SYSTEM_PROMPT, user_prompt


def _bullet_list(items: List[str]) -> str:
    if not items:
        return "(none noted)"
    return "\n".join(f"- {item}" for item in items)
