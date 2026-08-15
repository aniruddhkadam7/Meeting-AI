"""AgentAskService: the live single-question flow for Custom Agents.

Mirrors app/services/ask_service.py::AskService — one LLM call, no extra
retrieval/classification round trips, optimized for live-overlay latency —
but parameterized by an AgentAskRequest (role/description/custom
instructions/personalization) instead of being specific to Interview Mode.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator

from app.core.config import Settings, get_settings
from app.schemas.agent_ask import AgentAskRequest, AgentAskResponse
from app.services.agent_prompt_builder import build_ask_messages
from app.services.llm import LLMProvider, get_llm_provider

logger = logging.getLogger("app.agent_ask")

_MAX_TOKENS_BY_LENGTH = {
    "concise": 120,
    "balanced": 220,
    "detailed": 400,
    "adaptive": 280,
}


class AgentAskService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)

    def _max_tokens(self, request: AgentAskRequest) -> int:
        return _MAX_TOKENS_BY_LENGTH[request.personalization.answer_length]

    async def ask(self, request: AgentAskRequest) -> AgentAskResponse:
        start = time.perf_counter()
        answer = await self._provider.generate(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[AGENT_ASK] agent_id=%s latency_ms=%.1f question_len=%d",
            request.agent_id, latency_ms, len(request.question),
        )
        return AgentAskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: AgentAskRequest) -> AsyncIterator[str]:
        start = time.perf_counter()
        first_token_ms: float | None = None

        async for delta in self._provider.stream(
            build_ask_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        ):
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - start) * 1000
            yield delta

        total_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[AGENT_ASK] agent_id=%s stream complete first_token_ms=%s total_ms=%.1f",
            request.agent_id,
            f"{first_token_ms:.1f}" if first_token_ms is not None else "n/a",
            total_ms,
        )


def get_agent_ask_service() -> AgentAskService:
    return AgentAskService()
