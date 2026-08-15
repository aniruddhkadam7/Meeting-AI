from __future__ import annotations

from typing import AsyncIterator, List

from .base import LLMMessage, LLMProvider


class AnthropicProvider(LLMProvider):
    """Not implemented in Phase 1 (spec section 31: "prepare architecture
    for... but only implement OpenAI initially"). Exists so the
    `LLMProvider` interface and `get_llm_provider()` selection logic don't
    need to change shape when a real implementation is added later.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        raise NotImplementedError("AnthropicProvider is not implemented in Phase 1")

    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("AnthropicProvider is not implemented in Phase 1")
        yield ""  # pragma: no cover - unreachable, keeps this an async generator
