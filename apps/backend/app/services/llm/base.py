from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, List, Literal


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    """Every provider implementation must be safe to call repeatedly (no
    hidden shared mutable state across calls) since the analysis pipeline
    calls `generate()` once per question plus once for the overall summary.
    """

    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        """Returns the complete model response as a string (not yet parsed as
        JSON — callers are responsible for validating/parsing structured
        output, per spec section 16's "accumulate and validate at completion"
        guidance)."""
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        """Yields response text incrementally. Used only for progress-style
        UI updates (e.g. "Generating feedback...") — never for rendering raw
        partial JSON directly, per spec section 16."""
        raise NotImplementedError
