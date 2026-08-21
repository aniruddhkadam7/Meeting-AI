from __future__ import annotations

import logging
from typing import AsyncIterator, List

from google import genai
from google.genai import types

from .base import LLMMessage, LLMProvider

logger = logging.getLogger("app.llm.gemini")

# `settings.llm_model`/`settings.ask_model` default to an OpenAI model string
# (see core/config.py's LLM_MODEL="gpt-4o-mini" default) since OpenAI was the
# only real provider originally — same substitution AnthropicProvider does.
_DEFAULT_MODEL = "gemini-3.6-flash"

# Gemini's `max_output_tokens` caps thinking tokens AND the visible answer
# together — unlike OpenAI/Anthropic, where a `max_tokens` budget only ever
# limits the visible answer. gemini-3.6-flash cannot disable thinking
# entirely (`thinking_budget=0` is rejected with a 400 — this model line
# always spends *some* reasoning budget), and a low explicit token budget
# (e.g. 128) doesn't reduce it either — measured `thoughts_token_count`
# stayed ~475-480 regardless. `thinking_level=MINIMAL`, by contrast,
# collapses that internal reasoning step down to effectively nothing
# (`thoughts_token_count` comes back `None`) and puts the entire requested
# budget toward the visible answer instead — this is the properly-supported
# low-token control (the newer sibling of `thinking_budget`), not a
# workaround, so callers' existing `max_tokens` values need no padding.
_THINKING_LEVEL = types.ThinkingLevel.MINIMAL


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        # The API key is only ever read from server-side config
        # (app/core/config.py <- GEMINI_API_KEY env var) and passed directly
        # to the SDK client here — same handling as the other providers.
        self._client = genai.Client(api_key=api_key)
        self._model = model if model.startswith("gemini-") else _DEFAULT_MODEL

    @staticmethod
    def _split_system(messages: List[LLMMessage]) -> tuple[str | None, List[types.Content]]:
        """Gemini takes a system instruction as a separate config field, not
        a message in `contents` — same shape mismatch as Anthropic's `system`
        param (see AnthropicProvider._split_system). Gemini also uses "model"
        rather than "assistant" as the non-user role name."""
        system_parts = [m.content for m in messages if m.role == "system"]
        turns = [
            types.Content(
                role="model" if m.role == "assistant" else "user",
                parts=[types.Part(text=m.content)],
            )
            for m in messages
            if m.role != "system"
        ]
        system = "\n\n".join(system_parts) if system_parts else None
        return system, turns

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        system, turns = self._split_system(messages)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=turns,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                thinking_config=types.ThinkingConfig(thinking_level=_THINKING_LEVEL),
            ),
        )
        return response.text or ""

    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        system, turns = self._split_system(messages)
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=turns,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                thinking_config=types.ThinkingConfig(thinking_level=_THINKING_LEVEL),
            ),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
