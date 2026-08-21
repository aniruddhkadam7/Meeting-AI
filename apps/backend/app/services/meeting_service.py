"""Meeting Mode services: the live ask flow and the end-of-meeting summary.

Mirrors app/services/sales_service.py (which itself mirrors
app/services/ask_service.py's live flow and app/services/analysis_service.py's
structured-JSON pattern).
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.meeting import MeetingAskRequest, MeetingAskResponse, MeetingSummary, MeetingSummaryRequest
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider
from app.services.prompt_builder_meeting import build_ask_messages, build_summary_prompt

logger = logging.getLogger("app.meeting")


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


class MeetingService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)
        self._injected_provider = provider is not None

    def _provider_for(self, request: MeetingAskRequest) -> LLMProvider:
        # A test-injected provider always wins — see AskService._provider_for
        # for the same rationale.
        if self._injected_provider or request.llm_provider is None:
            return self._provider
        return get_llm_provider(self._settings, model=self._settings.ask_model, provider=request.llm_provider)

    def _max_tokens(self, request: MeetingAskRequest) -> int:
        if request.answer_length == "brief":
            return 120
        if request.answer_length == "detailed":
            return 300
        return 180

    async def ask(self, request: MeetingAskRequest) -> MeetingAskResponse:
        start = time.perf_counter()
        answer = await self._provider_for(request).generate(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return MeetingAskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: MeetingAskRequest) -> AsyncIterator[str]:
        async for delta in self._provider_for(request).stream(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        ):
            yield delta

    async def summarize(self, request: MeetingSummaryRequest) -> MeetingSummary:
        if not request.turns:
            return MeetingSummary(
                summary="No conversation was captured for this meeting.",
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
            return MeetingSummary(
                summary=parsed.get("summary", ""),
                key_points=list(parsed.get("key_points", [])),
                decisions=list(parsed.get("decisions", [])),
                action_items=list(parsed.get("action_items", [])),
                next_steps=list(parsed.get("next_steps", [])),
            )
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[MEETING] summary generation failed error=%s", exc)
            return MeetingSummary(
                summary="",
                key_points=list(request.key_points),
                decisions=list(request.decisions),
                action_items=list(request.action_items),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )
        except Exception as exc:  # provider-level failures
            logger.error("[MEETING] LLM call failed error=%s", exc)
            return MeetingSummary(
                summary="",
                key_points=list(request.key_points),
                decisions=list(request.decisions),
                action_items=list(request.action_items),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )


def get_meeting_service() -> MeetingService:
    return MeetingService()
