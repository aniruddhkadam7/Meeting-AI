"""Sales Mode services: the live ask flow and the end-of-call summary.

Mirrors app/services/ask_service.py (live flow) and
app/services/analysis_service.py's structured-JSON pattern (summary flow).
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.sales import SalesAskRequest, SalesAskResponse, SalesCallSummary, SalesSummaryRequest
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider
from app.services.prompt_builder_sales import build_ask_messages, build_summary_prompt

logger = logging.getLogger("app.sales")


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


class SalesService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)

    def _max_tokens(self, request: SalesAskRequest) -> int:
        if request.answer_length == "brief":
            return 120
        if request.answer_length == "detailed":
            return 300
        return 180

    async def ask(self, request: SalesAskRequest) -> SalesAskResponse:
        start = time.perf_counter()
        answer = await self._provider.generate(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return SalesAskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: SalesAskRequest) -> AsyncIterator[str]:
        async for delta in self._provider.stream(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        ):
            yield delta

    async def summarize(self, request: SalesSummaryRequest) -> SalesCallSummary:
        if not request.turns:
            return SalesCallSummary(
                summary="No conversation was captured for this call.",
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
            return SalesCallSummary(
                summary=parsed.get("summary", ""),
                key_requirements=list(parsed.get("key_requirements", [])),
                key_objections=list(parsed.get("key_objections", [])),
                commitments=list(parsed.get("commitments", [])),
                action_items=list(parsed.get("action_items", [])),
                next_steps=list(parsed.get("next_steps", [])),
                buying_intent=parsed.get("buying_intent", "unknown"),
            )
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[SALES] summary generation failed error=%s", exc)
            return SalesCallSummary(
                summary="",
                key_requirements=list(request.requirements),
                key_objections=list(request.objections),
                commitments=list(request.commitments),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )
        except Exception as exc:  # provider-level failures
            logger.error("[SALES] LLM call failed error=%s", exc)
            return SalesCallSummary(
                summary="",
                key_requirements=list(request.requirements),
                key_objections=list(request.objections),
                commitments=list(request.commitments),
                message=f"AI summary could not be generated ({exc}); showing tracked items only.",
            )


def get_sales_service() -> SalesService:
    return SalesService()
