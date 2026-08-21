"""LLMProvider abstraction.

    LLMProvider
    +-- OpenAIProvider     (implemented, active when LLM_PROVIDER=openai and
    |                       OPENAI_API_KEY is set)
    +-- AnthropicProvider  (implemented, active when LLM_PROVIDER=anthropic and
    |                       ANTHROPIC_API_KEY is set)
    +-- GeminiProvider     (implemented, active when LLM_PROVIDER=gemini and
    |                       GEMINI_API_KEY is set)
    +-- MockLLMProvider    (deterministic, no API key, no network call — used
                            whenever no real provider is configured/available)

The rest of the application (prompt building, analysis orchestration) only
ever calls `LLMProvider.generate()`/`LLMProvider.stream()` — it never knows or
cares whether the underlying model is OpenAI, Anthropic, Gemini, or a mock.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings

from .anthropic_provider import AnthropicProvider
from .base import LLMMessage, LLMProvider
from .gemini_provider import GeminiProvider
from .mock_provider import MockLLMProvider
from .openai_provider import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "LLMMessage",
    "LLMProvider",
    "MockLLMProvider",
    "OpenAIProvider",
    "get_llm_provider",
]


def get_llm_provider(
    settings: Settings | None = None, model: str | None = None, provider: str | None = None
) -> LLMProvider:
    """Selects a provider based on configuration, falling back to the mock
    provider whenever the configured real provider isn't actually usable
    (missing API key, unrecognized provider name) rather than raising — the
    analysis pipeline should degrade to an obviously-labeled mock result
    instead of crashing when misconfigured.

    `model` overrides the configured `LLM_MODEL` for this provider instance
    only. Interview Mode uses it to run its live answers on a faster/cheaper
    model (`ASK_LLM_MODEL`) than the offline analysis pipeline.

    `provider` overrides the configured `LLM_PROVIDER` for this call only —
    e.g. the desktop app's per-request model-provider dropdown. `None` keeps
    the server-configured default, so existing callers that don't pass it are
    unaffected.
    """
    settings = settings or get_settings()
    provider = provider or settings.llm_provider

    if provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(api_key=settings.openai_api_key, model=model or settings.llm_model)

    if provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=model or settings.llm_model)

    if provider == "gemini" and settings.gemini_api_key:
        return GeminiProvider(api_key=settings.gemini_api_key, model=model or settings.llm_model)

    return MockLLMProvider()
