"""Consulting Mode services: the live ask flow and the end-of-session
structured notes summary. Mirrors app/services/sales_service.py.
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.consulting import (
    ConsultingAskRequest,
    ConsultingAskResponse,
    ConsultingNote,
    ConsultingSummaryRequest,
)
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider
from app.services.prompt_builder_consulting import build_ask_messages, build_summary_prompt

logger = logging.getLogger("app.consulting")


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


class ConsultingService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)

    def _max_tokens(self, request: ConsultingAskRequest) -> int:
        if request.answer_length == "brief":
            return 120
        if request.answer_length == "detailed":
            return 300
        return 180

    async def ask(self, request: ConsultingAskRequest) -> ConsultingAskResponse:
        start = time.perf_counter()
        answer = await self._provider.generate(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return ConsultingAskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: ConsultingAskRequest) -> AsyncIterator[str]:
        async for delta in self._provider.stream(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        ):
            yield delta

    async def summarize(self, request: ConsultingSummaryRequest) -> ConsultingNote:
        if not request.turns:
            return ConsultingNote(
                summary="No conversation was captured for this session.",
                message="No transcript turns were provided.",
            )

        system_prompt, user_prompt = build_summary_prompt(request)
        try:
            raw = await self._provider.generate(
                [LLMMessage("system", system_prompt), LLMMessage("user", user_prompt)],
                temperature=0.2,
                max_tokens=self._settings.max_output_tokens,
            )
            parsed = _extract_json_object(raw)
            return ConsultingNote(
                summary=parsed.get("summary", ""),
                key_points=list(parsed.get("key_points", [])),
                risks=list(parsed.get("risks", [])),
                assumptions=list(parsed.get("assumptions", [])),
                decisions=list(parsed.get("decisions", [])),
                dependencies=list(parsed.get("dependencies", [])),
                action_items=list(parsed.get("action_items", [])),
                open_questions=list(parsed.get("open_questions", [])),
            )
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[CONSULTING] summary generation failed error=%s", exc)
            return ConsultingNote(
                summary="",
                risks=list(request.risks),
                assumptions=list(request.assumptions),
                decisions=list(request.decisions),
                dependencies=list(request.dependencies),
                action_items=list(request.action_items),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )
        except Exception as exc:  # provider-level failures
            logger.error("[CONSULTING] LLM call failed error=%s", exc)
            return ConsultingNote(
                summary="",
                risks=list(request.risks),
                assumptions=list(request.assumptions),
                decisions=list(request.decisions),
                dependencies=list(request.dependencies),
                action_items=list(request.action_items),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )


def get_consulting_service() -> ConsultingService:
    return ConsultingService()
