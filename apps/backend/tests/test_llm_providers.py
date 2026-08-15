import json

import pytest

from app.core.config import Settings
from app.services.llm import get_llm_provider
from app.services.llm.base import LLMMessage
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


def test_get_llm_provider_falls_back_to_mock_for_anthropic_stub():
    settings = Settings()
    settings.llm_provider = "anthropic"
    settings.anthropic_api_key = "fake-key"
    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_get_llm_provider_selects_openai_when_configured():
    settings = Settings()
    settings.llm_provider = "openai"
    settings.openai_api_key = "sk-fake-test-key"
    settings.llm_model = "gpt-4o-mini"
    provider = get_llm_provider(settings)
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.asyncio
async def test_anthropic_provider_stub_raises_not_implemented():
    from app.services.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", model="claude-fake")
    with pytest.raises(NotImplementedError):
        await provider.generate([LLMMessage("user", "test")])
