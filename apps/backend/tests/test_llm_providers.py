import json

import pytest

from app.core.config import Settings
from app.services.llm import get_llm_provider
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMMessage
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import OpenAIProvider


@pytest.mark.asyncio
async def test_mock_provider_generate_returns_valid_json():
    provider = MockLLMProvider()
    result = await provider.generate([LLMMessage("user", "test prompt")])
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_mock_provider_detects_question_level_prompt():
    provider = MockLLMProvider()
    result = await provider.generate([LLMMessage("user", '..."question_id"...')])
    parsed = json.loads(result)
    assert "assessment" in parsed
    assert "score" in parsed


@pytest.mark.asyncio
async def test_mock_provider_detects_overall_prompt():
    provider = MockLLMProvider()
    result = await provider.generate([LLMMessage("user", "produce overall_score and summary")])
    parsed = json.loads(result)
    assert "overall_score" in parsed
    assert "summary" in parsed


@pytest.mark.asyncio
async def test_mock_provider_never_returns_nonzero_scores():
    provider = MockLLMProvider()
    result = await provider.generate([LLMMessage("user", "overall_score summary")])
    parsed = json.loads(result)
    assert parsed["overall_score"] == 0


@pytest.mark.asyncio
async def test_mock_provider_stream_yields_full_content_when_joined():
    provider = MockLLMProvider()
    chunks = []
    async for chunk in provider.stream([LLMMessage("user", "test")]):
        chunks.append(chunk)
    full = "".join(chunks)
    parsed = json.loads(full)
    assert isinstance(parsed, dict)


def test_get_llm_provider_falls_back_to_mock_when_no_api_key():
    settings = Settings()
    settings.llm_provider = "openai"
    settings.openai_api_key = None
    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_get_llm_provider_falls_back_to_mock_for_unrecognized_provider():
    settings = Settings()
    settings.llm_provider = "not-a-real-provider"
    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_get_llm_provider_selects_anthropic_when_configured():
    settings = Settings()
    settings.llm_provider = "anthropic"
    settings.anthropic_api_key = "fake-key"
    provider = get_llm_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_get_llm_provider_falls_back_to_mock_when_anthropic_key_missing():
    settings = Settings()
    settings.llm_provider = "anthropic"
    settings.anthropic_api_key = None
    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_get_llm_provider_honors_per_request_provider_override():
    settings = Settings()
    settings.llm_provider = "openai"
    settings.openai_api_key = "sk-fake-test-key"
    settings.anthropic_api_key = "fake-key"
    provider = get_llm_provider(settings, provider="anthropic")
    assert isinstance(provider, AnthropicProvider)


def test_get_llm_provider_selects_openai_when_configured():
    settings = Settings()
    settings.llm_provider = "openai"
    settings.openai_api_key = "sk-fake-test-key"
    settings.llm_model = "gpt-4o-mini"
    provider = get_llm_provider(settings)
    assert isinstance(provider, OpenAIProvider)


def test_anthropic_provider_substitutes_default_model_for_non_claude_model_string():
    # settings.llm_model defaults to an OpenAI model string (see
    # core/config.py) — AnthropicProvider must not send that to Anthropic's
    # API just because it was passed through unchanged.
    provider = AnthropicProvider(api_key="fake", model="gpt-4o-mini")
    assert provider._model.startswith("claude-")


def test_anthropic_provider_keeps_explicit_claude_model_string():
    provider = AnthropicProvider(api_key="fake", model="claude-opus-5")
    assert provider._model == "claude-opus-5"


def test_get_llm_provider_selects_gemini_when_configured():
    settings = Settings()
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "fake-key"
    provider = get_llm_provider(settings)
    assert isinstance(provider, GeminiProvider)


def test_get_llm_provider_falls_back_to_mock_when_gemini_key_missing():
    settings = Settings()
    settings.llm_provider = "gemini"
    settings.gemini_api_key = None
    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_gemini_provider_substitutes_default_model_for_non_gemini_model_string():
    # settings.llm_model defaults to an OpenAI model string (see
    # core/config.py) — GeminiProvider must not send that to Gemini's API
    # just because it was passed through unchanged.
    provider = GeminiProvider(api_key="fake", model="gpt-4o-mini")
    assert provider._model.startswith("gemini-")


def test_gemini_provider_keeps_explicit_gemini_model_string():
    provider = GeminiProvider(api_key="fake", model="gemini-2.5-pro")
    assert provider._model == "gemini-2.5-pro"


def test_gemini_provider_splits_system_message_out_of_contents():
    system, turns = GeminiProvider._split_system(
        [
            LLMMessage("system", "You are helpful."),
            LLMMessage("user", "Hi"),
            LLMMessage("assistant", "Hello!"),
        ]
    )
    assert system == "You are helpful."
    assert [t.role for t in turns] == ["user", "model"]
