"""LLMProvider abstraction.

    LLMProvider
    +-- OpenAIProvider     (implemented, active when LLM_PROVIDER=openai and
    |                       OPENAI_API_KEY is set)
    +-- AnthropicProvider  (stub — raises NotImplementedError; the interface
    |                       exists so a real implementation can be dropped in
    |                       later without touching callers)
    +-- MockLLMProvider    (deterministic, no API key, no network call — used
                            whenever no real provider is configured/available)

The rest of the application (prompt building, analysis orchestration) only
ever calls `LLMProvider.generate()`/`LLMProvider.stream()` — it never knows or
cares whether the underlying model is OpenAI, Anthropic, or a mock.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings

from .base import LLMMessage, LLMProvider
from .mock_provider import MockLLMProvider
from .openai_provider import OpenAIProvider

__all__ = ["LLMMessage", "LLMProvider", "MockLLMProvider", "OpenAIProvider", "get_llm_provider"]


def get_llm_provider(settings: Settings | None = None, model: str | None = None) -> LLMProvider:
    """Selects a provider based on configuration, falling back to the mock
    provider whenever the configured real provider isn't actually usable
    (missing API key, unrecognized provider name) rather than raising — the
    analysis pipeline should degrade to an obviously-labeled mock result
    instead of crashing when misconfigured.

    `model` overrides the configured `LLM_MODEL` for this provider instance
    only. Interview Mode uses it to run its live answers on a faster/cheaper
    model (`ASK_LLM_MODEL`) than the offline analysis pipeline.
    """
    settings = settings or get_settings()

    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(api_key=settings.openai_api_key, model=model or settings.llm_model)

    if settings.llm_provider == "anthropic":
        # AnthropicProvider is a stub for Phase 1 (spec section 31: "prepare
        # architecture for... but only implement OpenAI initially") — fall
        # back to mock rather than raise, so an accidental
        # LLM_PROVIDER=anthropic doesn't take the whole analysis feature down.
        return MockLLMProvider()

    return MockLLMProvider()
