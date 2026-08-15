from __future__ import annotations

import logging
from typing import AsyncIterator, List

from openai import AsyncOpenAI

from .base import LLMMessage, LLMProvider

logger = logging.getLogger("app.llm.openai")


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        # The API key is only ever read from server-side config
        # (app/core/config.py <- OPENAI_API_KEY env var) and passed directly
        # to the SDK client here — it is never logged, never included in any
        # response body, and never reachable from the frontend.
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
