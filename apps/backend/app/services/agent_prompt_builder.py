"""System prompt composer for Custom Agents.

One generic builder instead of a `prompt_builder_<role>.py` per predefined
role or per custom agent — mirrors `prompt_builder_sales.py::build_ask_messages`
(system prompt once, replayed conversation turns, one user message carrying
context + the question + a trailing length/style/format instruction) but
assembles the system prompt itself from data (`agent_roles.py`) plus the
user's own free-text description/custom instructions, rather than a
hardcoded prompt file per role.

This is the mechanism behind "Smallbird should automatically convert simple
inputs into internal instructions" — the composed prompt below is never
shown to the user and never needs to be written by them.
"""

from __future__ import annotations

from typing import List

from app.schemas.agent_ask import AgentAskRequest
from app.services.agent_roles import get_role_prompt
from app.services.llm import LLMMessage

_LENGTH_INSTRUCTIONS = {
    "concise": "Ceiling: 1-3 sentences. Be maximally direct.",
    "balanced": "Ceiling: roughly 40-90 words — enough for a real answer, never an essay.",
    "detailed": "Ceiling: roughly 120-200 words for a question that genuinely needs the depth.",
    "adaptive": (
        "Judge the right length from the question itself — a short factual question gets 1-3 "
        "sentences, a question that genuinely asks for depth or process earns more room. Never "
        "pad a simple answer and never compress one that needs structure."
    ),
}

_STYLE_INSTRUCTIONS = {
    "natural": "Sound like a real, knowledgeable person talking, not a generated answer.",
    "professional": "Clear, polished, workplace-appropriate language — but still plainly spoken, not stiff.",
    "friendly": "Warm and approachable, like a helpful colleague, while staying useful and direct.",
    "technical": "Lean technical: precise terminology and concrete detail, still said out loud, not lectured.",
}

_FORMAT_INSTRUCTIONS = {
    "paragraph": "Answer in plain prose — no headings, no bullet points, no numbered steps.",
    "bullets": "Use short Markdown bullet points for the distinct pieces of the answer.",
    "step_by_step": "Use a Markdown numbered list (1. 2. 3. ...), one concrete step per line.",
    "adaptive": (
        "Pick whatever format actually fits the answer — plain sentences for something simple, "
        "bullets for a set of distinct points, numbered steps for a process. Never force structure "
        "onto an answer that doesn't need it, and never write a wall of text for one that does."
    ),
}


def _build_system_prompt(request: AgentAskRequest) -> str:
    role = get_role_prompt(request.base_role)

    parts: List[str] = [
        f"You are {request.agent_name}, {role.persona}, speaking to {role.audience}.",
    ]

    if role.voice_notes:
        parts.append("\n".join(f"- {note}" for note in role.voice_notes))

    if request.description:
        parts.append(f"What this assistant is for: {request.description}")

    parts.append(
        "HOW TO ANSWER\n\n"
        "Answer the question that was actually asked, directly and usefully. Ground the answer "
        "in whatever background context is given when it's relevant, and in your own general "
        "knowledge otherwise — missing or thin background is normal and never a reason to say you "
        "lack information or to mention documents, sources, or retrieval. No preamble, no "
        "meta-commentary about being an AI assistant, no restating the question before answering it. "
        "Do not invent specific facts, figures, names, or commitments that aren't supported by the "
        "context you were given."
    )

    if request.custom_instructions:
        # Appended last and verbatim, additive to (never replacing) the
        # persona/voice/honesty rules above — the user's own instructions
        # are extra guidance, not a license to override the safety rules.
        parts.append(f"ADDITIONAL INSTRUCTIONS FROM THE USER:\n{request.custom_instructions}")

    return "\n\n".join(parts)


def _context_blocks(request: AgentAskRequest) -> List[str]:
    blocks: List[str] = []
    if request.retrieved_context:
        chunks = "\n\n".join(chunk.text for chunk in request.retrieved_context)
        blocks.append(f"Background notes:\n{chunks}")
    return blocks


def _build_user_prompt(request: AgentAskRequest) -> str:
    parts: List[str] = []

    blocks = _context_blocks(request)
    if blocks:
        parts.append(
            "SUPPORTING BACKGROUND (optional — use only what's relevant; never mention it as a "
            "source):\n\n" + "\n\n".join(blocks)
        )

    parts.append(f"The question:\n{request.question}")

    personalization = request.personalization
    parts.append(
        f"{_LENGTH_INSTRUCTIONS[personalization.answer_length]}\n"
        f"{_FORMAT_INSTRUCTIONS[personalization.answer_format]}\n"
        f"{_STYLE_INSTRUCTIONS[personalization.response_style]}\n\n"
        "Reply with the answer only."
    )

    return "\n\n---\n\n".join(parts)


def build_ask_messages(request: AgentAskRequest) -> List[LLMMessage]:
    """system prompt -> prior turns -> the current question, matching the
    shape used by every other mode's ask flow (see app/services/ask_service.py)
    so follow-ups resolve against the model's own prior answers."""
    messages: List[LLMMessage] = [LLMMessage("system", _build_system_prompt(request))]

    for turn in request.conversation_history:
        messages.append(LLMMessage("user", turn.question))
        messages.append(LLMMessage("assistant", turn.answer))

    messages.append(LLMMessage("user", _build_user_prompt(request)))
    return messages
