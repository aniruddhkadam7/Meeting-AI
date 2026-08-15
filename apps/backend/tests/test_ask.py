import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.schemas.ask import AskRequest
from app.services.ask_service import SYSTEM_PROMPT, AskService, _build_user_prompt
from app.services.llm.base import LLMMessage, LLMProvider

client = TestClient(app)

ENDPOINT = "/api/v1/ask"


def _payload(**overrides):
    payload = {
        "question": "What is your experience with Python?",
        "retrieved_context": [
            {
                "text": "5 years of Python experience building web APIs.",
                "source_filename": "resume.pdf",
                "document_type": "RESUME",
                "score": 0.9,
            }
        ],
        "candidate_context": None,
    }
    payload.update(overrides)
    return payload


def test_ask_returns_200_with_mock_provider():
    response = client.post(ENDPOINT, json=_payload())
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "latency_ms" in body


def test_ask_missing_question_returns_422():
    payload = _payload()
    del payload["question"]
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_ask_empty_question_returns_422():
    response = client.post(ENDPOINT, json=_payload(question=""))
    assert response.status_code == 422


def test_ask_with_no_retrieved_context_still_works():
    response = client.post(ENDPOINT, json=_payload(retrieved_context=[]))
    assert response.status_code == 200


def test_ask_with_candidate_context_string():
    response = client.post(ENDPOINT, json=_payload(candidate_context="Senior backend engineer."))
    assert response.status_code == 200


def test_ask_oversized_chunk_returns_422():
    payload = _payload()
    payload["retrieved_context"][0]["text"] = "x" * 5000
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


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
async def test_ask_service_uses_short_conversational_prompt():
    provider = ScriptedLLMProvider("I have five years of Python experience.")
    service = AskService(provider=provider, settings=Settings())
    request = AskRequest(**_payload())
    result = await service.ask(request)

    assert result.answer == "I have five years of Python experience."
    assert provider.last_messages[0].role == "system"
    assert provider.last_messages[0].content == SYSTEM_PROMPT
    assert "first person" in SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_system_prompt_forbids_document_references():
    """The overlay answer must read as a person speaking, never as a summary
    of uploaded files — every one of these phrasings is explicitly banned."""
    lowered = SYSTEM_PROMPT.lower()
    assert "according to your resume" in lowered
    assert "based on the retrieved context" in lowered
    assert "the provided documents indicate" in lowered
    assert "i don't have enough information in the uploaded documents" in lowered


@pytest.mark.asyncio
async def test_system_prompt_makes_context_optional_not_required():
    """Missing context must be framed as a non-event, so a question the CV
    says nothing about still gets a real answer from general knowledge."""
    lowered = SYSTEM_PROMPT.lower()
    assert "general knowledge" in lowered
    assert "not a boundary" in lowered


@pytest.mark.asyncio
async def test_ask_service_includes_question_and_context_in_user_prompt():
    request = AskRequest(**_payload())
    prompt = _build_user_prompt(request)
    assert "What is your experience with Python?" in prompt
    assert "5 years of Python experience building web APIs." in prompt


@pytest.mark.asyncio
async def test_ask_user_prompt_omits_source_filenames():
    """Filenames in the prompt invite "according to resume.pdf..." citations
    and add nothing to the answer, so only chunk substance is passed through."""
    request = AskRequest(**_payload())
    prompt = _build_user_prompt(request)
    assert "resume.pdf" not in prompt
    assert "RESUME" not in prompt


@pytest.mark.asyncio
async def test_ask_user_prompt_has_no_missing_context_placeholder():
    """A "(no context available)" placeholder plants the idea of missing
    documents and is what produces "not found in your documents" answers —
    with nothing retrieved, the context section is omitted entirely."""
    request = AskRequest(question="What is Kubernetes?", retrieved_context=[], candidate_context=None)
    prompt = _build_user_prompt(request)
    assert "What is Kubernetes?" in prompt
    assert "SUPPORTING BACKGROUND" not in prompt
    assert "no candidate context" not in prompt.lower()


@pytest.mark.asyncio
async def test_ask_user_prompt_includes_role_and_job_description():
    request = AskRequest(
        question="Why do you want this role?",
        role="Senior Backend Engineer",
        job_description="Building distributed payment systems.",
    )
    prompt = _build_user_prompt(request)
    assert "Senior Backend Engineer" in prompt
    assert "Building distributed payment systems." in prompt


@pytest.mark.asyncio
async def test_ask_answer_length_and_style_reach_the_prompt():
    brief = _build_user_prompt(AskRequest(question="What is RAG?", answer_length="brief"))
    assert "1-3 sentences" in brief

    default = _build_user_prompt(AskRequest(question="What is RAG?"))
    assert "50-120 words" in default

    concise = _build_user_prompt(AskRequest(question="What is RAG?", response_style="concise"))
    assert "direct" in concise.lower()


@pytest.mark.asyncio
async def test_brief_answers_get_a_smaller_token_budget():
    settings = Settings()
    settings.max_answer_tokens = 250
    service = AskService(provider=ScriptedLLMProvider("ok"), settings=settings)

    assert service._max_tokens(AskRequest(question="q", answer_length="brief")) == 120
    assert service._max_tokens(AskRequest(question="q")) == 250
    assert service._max_tokens(AskRequest(question="q", answer_length="detailed")) == 400


@pytest.mark.asyncio
async def test_ask_stream_yields_deltas():
    provider = ScriptedLLMProvider("Full answer text.")
    service = AskService(provider=provider, settings=Settings())
    request = AskRequest(**_payload())

    chunks = []
    async for delta in service.ask_stream(request):
        chunks.append(delta)
    assert "".join(chunks) == "Full answer text."


@pytest.mark.asyncio
async def test_ask_respects_max_answer_tokens_setting():
    settings = Settings()
    settings.max_answer_tokens = 42

    captured = {}

    class CapturingProvider(LLMProvider):
        async def generate(self, messages, temperature=0.2, max_tokens=1500):
            captured["max_tokens"] = max_tokens
            return "ok"

        async def stream(self, messages, temperature=0.2, max_tokens=1500):
            yield "ok"

    service = AskService(provider=CapturingProvider(), settings=settings)
    await service.ask(AskRequest(**_payload()))
    assert captured["max_tokens"] == 42


# --- conversation history (Interview Mode follow-up questions) ---------------


def test_ask_accepts_conversation_history():
    response = client.post(
        ENDPOINT,
        json=_payload(
            question="Why did you choose that?",
            conversation_history=[
                {"question": "How do you do retrieval?", "answer": "I use semantic search."}
            ],
        ),
    )
    assert response.status_code == 200


def test_ask_without_history_still_works():
    """The first question of a session sends none — must behave as before."""
    response = client.post(ENDPOINT, json=_payload())
    assert response.status_code == 200


def test_history_becomes_real_conversation_turns():
    """Prior turns must be replayed as user/assistant messages, not flattened
    into the prompt text. That is what lets the model resolve "that" in a
    follow-up against its own previous answer."""
    from app.services.ask_service import _build_messages

    request = AskRequest(
        question="Why did you choose that?",
        conversation_history=[
            {"question": "How do you do retrieval?", "answer": "I use semantic search."},
            {"question": "What embeds it?", "answer": "A sentence-transformers model."},
        ],
    )
    messages = _build_messages(request)

    assert messages[0].role == "system"
    # Two prior turns -> four replayed messages, in order, oldest first.
    assert [m.role for m in messages[1:5]] == ["user", "assistant", "user", "assistant"]
    assert messages[1].content == "How do you do retrieval?"
    assert messages[2].content == "I use semantic search."
    assert messages[3].content == "What embeds it?"
    assert messages[4].content == "A sentence-transformers model."
    # The current question is last, and carries the instructions.
    assert messages[-1].role == "user"
    assert "Why did you choose that?" in messages[-1].content


def test_history_turns_carry_no_instructions_or_context():
    """Only the bare Q/A text is replayed. Repeating the length/style
    instructions or old retrieval context on every turn would bloat the prompt
    and let stale context leak into a new answer."""
    from app.services.ask_service import _build_messages

    request = AskRequest(
        question="And how would you scale it?",
        conversation_history=[
            {"question": "How do you do retrieval?", "answer": "I use semantic search."}
        ],
        retrieved_context=[
            {
                "text": "Built a vector search service.",
                "source_filename": "resume.pdf",
                "document_type": "RESUME",
                "score": 0.9,
            }
        ],
    )
    messages = _build_messages(request)

    assert messages[1].content == "How do you do retrieval?"
    assert "SUPPORTING BACKGROUND" not in messages[1].content
    assert "Reply with the spoken answer only" not in messages[2].content
    # Retrieval context belongs to the current question alone.
    assert "Built a vector search service." in messages[-1].content


def test_system_prompt_explains_follow_ups():
    assert "follow-up" in SYSTEM_PROMPT.lower()


def test_history_is_capped():
    """Backstop against an unbounded prompt in a long interview."""
    from app.schemas.ask import MAX_HISTORY_TURNS

    too_many = [
        {"question": f"q{i}", "answer": f"a{i}"} for i in range(MAX_HISTORY_TURNS + 5)
    ]
    response = client.post(
        ENDPOINT, json=_payload(question="Follow up?", conversation_history=too_many)
    )
    assert response.status_code == 422
