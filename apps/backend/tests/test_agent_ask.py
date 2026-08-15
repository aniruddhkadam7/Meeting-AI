import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.schemas.agent_ask import AgentAskRequest
from app.services.agent_ask_service import AgentAskService
from app.services.agent_prompt_builder import build_ask_messages
from app.services.llm.base import LLMProvider

client = TestClient(app)

ENDPOINT = "/api/v1/agents/ask"


def _payload(**overrides):
    payload = {
        "agent_id": "agent_123",
        "agent_name": "My Sales Coach",
        "base_role": "SALESPERSON",
        "question": "How do I handle a price objection?",
    }
    payload.update(overrides)
    return payload


def test_agent_ask_returns_200_with_mock_provider():
    response = client.post(ENDPOINT, json=_payload())
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "latency_ms" in body


def test_agent_ask_missing_question_returns_422():
    payload = _payload()
    del payload["question"]
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_agent_ask_missing_agent_id_returns_422():
    payload = _payload()
    del payload["agent_id"]
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_agent_ask_works_without_base_role():
    """A fully Custom Agent (no predefined role) must still get a real
    answer via the generic persona, not an error."""
    response = client.post(ENDPOINT, json=_payload(base_role=None))
    assert response.status_code == 200


def test_agent_ask_rejects_unknown_base_role():
    response = client.post(ENDPOINT, json=_payload(base_role="NOT_A_REAL_ROLE"))
    assert response.status_code == 422


def test_agent_ask_with_no_retrieved_context_still_works():
    response = client.post(ENDPOINT, json=_payload(retrieved_context=[]))
    assert response.status_code == 200


def test_agent_ask_accepts_conversation_history():
    response = client.post(
        ENDPOINT,
        json=_payload(
            question="Why did you suggest that?",
            conversation_history=[
                {"question": "How do I open the call?", "answer": "Lead with the customer's stated goal."}
            ],
        ),
    )
    assert response.status_code == 200


def test_agent_ask_accepts_personalization():
    response = client.post(
        ENDPOINT,
        json=_payload(
            personalization={
                "answer_length": "concise",
                "response_style": "technical",
                "answer_format": "bullets",
                "live_assistance": "suggest",
            }
        ),
    )
    assert response.status_code == 200


class ScriptedLLMProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_messages = None

    async def generate(self, messages, temperature=0.2, max_tokens=1500) -> str:
        self.last_messages = messages
        return self._response

    async def stream(self, messages, temperature=0.2, max_tokens=1500):
        yield self._response


@pytest.mark.asyncio
async def test_predefined_role_persona_reaches_the_system_prompt():
    request = AgentAskRequest(**_payload(base_role="RECRUITER"))
    messages = build_ask_messages(request)
    assert messages[0].role == "system"
    assert "recruiting assistant" in messages[0].content.lower()


@pytest.mark.asyncio
async def test_custom_agent_without_base_role_gets_generic_persona():
    request = AgentAskRequest(**_payload(base_role=None))
    messages = build_ask_messages(request)
    assert "professional assistant" in messages[0].content.lower()


@pytest.mark.asyncio
async def test_agent_name_reaches_the_system_prompt():
    request = AgentAskRequest(**_payload(agent_name="Deal Desk Helper", base_role=None))
    messages = build_ask_messages(request)
    assert "Deal Desk Helper" in messages[0].content


@pytest.mark.asyncio
async def test_description_reaches_the_system_prompt():
    request = AgentAskRequest(
        **_payload(base_role=None, description="Helps close enterprise renewal deals.")
    )
    messages = build_ask_messages(request)
    assert "Helps close enterprise renewal deals." in messages[0].content


@pytest.mark.asyncio
async def test_custom_instructions_are_additive_and_appended_last():
    request = AgentAskRequest(
        **_payload(custom_instructions="Always mention our 30-day trial.")
    )
    messages = build_ask_messages(request)
    system_prompt = messages[0].content
    assert "Always mention our 30-day trial." in system_prompt
    # Additive: the shared honesty/voice rules must still be present, not
    # replaced by the user's own instructions.
    assert "do not invent" in system_prompt.lower()


@pytest.mark.asyncio
async def test_missing_custom_instructions_omits_that_section():
    request = AgentAskRequest(**_payload(custom_instructions=None))
    messages = build_ask_messages(request)
    assert "ADDITIONAL INSTRUCTIONS" not in messages[0].content


@pytest.mark.asyncio
async def test_personalization_reaches_the_user_prompt():
    from app.services.agent_prompt_builder import _build_user_prompt

    request = AgentAskRequest(
        **_payload(
            personalization={
                "answer_length": "concise",
                "response_style": "technical",
                "answer_format": "step_by_step",
                "live_assistance": "manual",
            }
        )
    )
    prompt = _build_user_prompt(request)
    assert "Ceiling: 1-3 sentences" in prompt
    assert "numbered list" in prompt.lower()
    assert "technical" in prompt.lower()


@pytest.mark.asyncio
async def test_default_personalization_is_adaptive():
    request = AgentAskRequest(**_payload())
    assert request.personalization.answer_length == "adaptive"
    assert request.personalization.answer_format == "adaptive"
    assert request.personalization.response_style == "natural"
    assert request.personalization.live_assistance == "manual"


@pytest.mark.asyncio
async def test_history_becomes_real_conversation_turns():
    request = AgentAskRequest(
        **_payload(
            question="Why did you suggest that?",
            conversation_history=[
                {"question": "How do I open the call?", "answer": "Lead with their stated goal."},
            ],
        )
    )
    messages = build_ask_messages(request)
    assert [m.role for m in messages[:3]] == ["system", "user", "assistant"]
    assert messages[1].content == "How do I open the call?"
    assert messages[2].content == "Lead with their stated goal."
    assert "Why did you suggest that?" in messages[-1].content


@pytest.mark.asyncio
async def test_ask_service_uses_composed_prompt():
    provider = ScriptedLLMProvider("Acknowledge the concern, then pivot to ROI.")
    service = AgentAskService(provider=provider, settings=Settings())
    request = AgentAskRequest(**_payload())
    result = await service.ask(request)

    assert result.answer == "Acknowledge the concern, then pivot to ROI."
    assert provider.last_messages[0].role == "system"


@pytest.mark.asyncio
async def test_max_tokens_varies_by_answer_length():
    settings = Settings()
    service = AgentAskService(provider=ScriptedLLMProvider("ok"), settings=settings)

    concise = AgentAskRequest(**_payload(personalization={"answer_length": "concise"}))
    detailed = AgentAskRequest(**_payload(personalization={"answer_length": "detailed"}))
    assert service._max_tokens(concise) < service._max_tokens(detailed)


@pytest.mark.asyncio
async def test_ask_stream_yields_deltas():
    provider = ScriptedLLMProvider("Full suggested answer.")
    service = AgentAskService(provider=provider, settings=Settings())
    request = AgentAskRequest(**_payload())

    chunks = []
    async for delta in service.ask_stream(request):
        chunks.append(delta)
    assert "".join(chunks) == "Full suggested answer."
