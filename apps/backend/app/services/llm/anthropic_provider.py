from __future__ import annotations

import logging
from typing import AsyncIterator, List

import anthropic

from .base import LLMMessage, LLMProvider

logger = logging.getLogger("app.llm.anthropic")

# `settings.llm_model`/`settings.ask_model` default to an OpenAI model string
# (see core/config.py's LLM_MODEL="gpt-4o-mini" default) since OpenAI was the
# only real provider until this one. If the caller passed that default
# through unchanged rather than a real Claude model ID, substitute Anthropic's
# own default instead of sending an OpenAI model name to this API.
_DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        # The API key is only ever read from server-side config
        # (app/core/config.py <- ANTHROPIC_API_KEY env var) and passed
        # directly to the SDK client here — same handling as OpenAIProvider.
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model if model.startswith("claude-") else _DEFAULT_MODEL

    @staticmethod
    def _split_system(messages: List[LLMMessage]) -> tuple[str | None, List[dict]]:
        """Anthropic's API takes `system` as a separate top-level parameter,
        not a message with role "system" in the `messages` list (unlike
        OpenAI's chat completions shape, which is what `LLMMessage` was
        modeled on) — pull any system-role messages out and join them."""
        system_parts = [m.content for m in messages if m.role == "system"]
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        system = "\n\n".join(system_parts) if system_parts else None
        return system, turns

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        system, turns = self._split_system(messages)
        response = await self._client.messages.create(
            model=self._model,
            system=system,
            messages=turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return "".join(block.text for block in response.content if block.type == "text")

    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        system, turns = self._split_system(messages)
        async with self._client.messages.stream(
            model=self._model,
            system=system,
            messages=turns,
            temperature=temperature,
            max_tokens=max_tokens,
        ) as stream:
            async for text in stream.text_stream:
                yield text
