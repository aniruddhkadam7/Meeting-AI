"""Notes Mode services: summarizing a note, and answering a question with one
or more notes as optional context. No live-call flow — see
app/schemas/notes.py.
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator, List

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.notes import NoteContext, NoteSummary, NotesAskRequest, NotesAskResponse, NotesSummaryRequest
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider

logger = logging.getLogger("app.notes")

SUMMARY_SYSTEM_PROMPT = """You extract structure from a personal/work note. \
Given the note's title and body, produce a short summary plus any tasks, \
decisions, and key points it contains.

Only extract what is actually present in the note — do not invent tasks or \
decisions that aren't there. If the note has no tasks, or no decisions, \
return an empty list for that field rather than inventing one.

You must respond with valid JSON only, matching exactly the schema described \
in the user message. Do not include any text outside the JSON object."""

ASK_SYSTEM_PROMPT = """You answer questions using the user's own notes as \
context, when relevant. The notes are supporting material, not a hard \
boundary: if they contain the answer, use it directly and naturally (never \
say "according to your notes" or similar); if they don't, answer from your \
own general knowledge instead of saying you don't have enough information.

Keep answers concise and directly useful — a few sentences, or a short list \
when the question calls for multiple points. No preamble."""


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start : end + 1])


def _build_ask_messages(request: NotesAskRequest) -> List[LLMMessage]:
    messages: List[LLMMessage] = [LLMMessage("system", ASK_SYSTEM_PROMPT)]
    parts: List[str] = []
    if request.notes:
        notes_block = "\n\n".join(_format_note(n) for n in request.notes)
        parts.append(f"NOTES:\n{notes_block}")
    parts.append(f"Question:\n{request.question}")
    messages.append(LLMMessage("user", "\n\n---\n\n".join(parts)))
    return messages


def _format_note(note: NoteContext) -> str:
    title = note.title or "(untitled)"
    return f"[{title}]\n{note.body}"


class NotesService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)

    async def summarize(self, request: NotesSummaryRequest) -> NoteSummary:
        user_prompt = f"""TITLE: {request.title or "(untitled)"}

BODY
{request.body}

Respond with a single JSON object matching exactly this schema:
{{
  "summary": "string — 1-3 sentence summary",
  "tasks": ["string", "..."],
  "decisions": ["string", "..."],
  "key_points": ["string", "..."]
}}"""
        try:
            raw = await self._provider.generate(
                [LLMMessage("system", SUMMARY_SYSTEM_PROMPT), LLMMessage("user", user_prompt)],
                temperature=0.2,
                max_tokens=self._settings.max_output_tokens,
            )
            parsed = _extract_json_object(raw)
            return NoteSummary(
                summary=parsed.get("summary", ""),
                tasks=list(parsed.get("tasks", [])),
                decisions=list(parsed.get("decisions", [])),
                key_points=list(parsed.get("key_points", [])),
            )
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[NOTES] summary generation failed error=%s", exc)
            return NoteSummary(message=f"AI summary could not be generated ({exc}).")
        except Exception as exc:
            logger.error("[NOTES] LLM call failed error=%s", exc)
            return NoteSummary(message=f"AI summary could not be generated ({exc}).")

    async def ask(self, request: NotesAskRequest) -> NotesAskResponse:
        start = time.perf_counter()
        answer = await self._provider.generate(
            _build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=250,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return NotesAskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: NotesAskRequest) -> AsyncIterator[str]:
        async for delta in self._provider.stream(
            _build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=250,
        ):
            yield delta


def get_notes_service() -> NotesService:
    return NotesService()
