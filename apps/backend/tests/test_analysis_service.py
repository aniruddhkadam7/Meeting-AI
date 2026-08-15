import json
from typing import AsyncIterator, List

import pytest

from app.core.config import Settings
from app.schemas.analysis import AnalysisStatus
from app.schemas.interview import CandidateContext, InterviewAnalysisRequest, QuestionAnswer, RetrievedChunk, Transcript
from app.services.analysis_service import AnalysisService
from app.services.llm.base import LLMMessage, LLMProvider


class ScriptedLLMProvider(LLMProvider):
    """Returns a pre-programmed sequence of responses, one per `generate()`
    call, so tests can control exactly what "the LLM" says without any
    network access. Raises if more calls happen than scripted responses were
    provided, or replays the last error if a provider-level exception was
    queued."""

    def __init__(self, responses: List[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: List[List[LLMMessage]] = []

    async def generate(self, messages, temperature=0.2, max_tokens=1500) -> str:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("ScriptedLLMProvider ran out of scripted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def stream(self, messages, temperature=0.2, max_tokens=1500) -> AsyncIterator[str]:
        text = await self.generate(messages, temperature, max_tokens)
        yield text


def _request(question_answers: List[QuestionAnswer]) -> InterviewAnalysisRequest:
    return InterviewAnalysisRequest(
        session_id="test-session",
        role="AI/ML Engineer",
        company="Example Co",
        job_description="Build ML systems.",
        candidate_context=CandidateContext(resume="Experienced engineer.", projects=["RAG Project"]),
        transcript=Transcript(duration_seconds=600, segments=[]),
        question_answers=question_answers,
    )


def _qa(question_id="q1", question="Explain RAG.", answer="I built a pipeline.") -> QuestionAnswer:
    return QuestionAnswer(
        question_id=question_id,
        question=question,
        candidate_answer=answer,
        timestamp="00:01:00",
        retrieved_context=[
            RetrievedChunk(text="RAG pipeline details.", source_filename="a.pdf", document_type="PROJECT", score=0.8)
        ],
    )


QUESTION_RESPONSE = json.dumps(
    {
        "assessment": "Solid technical explanation.",
        "score": 82,
        "strengths": ["Clear structure"],
        "issues": ["Could mention deployment"],
        "improved_answer": "I implemented a RAG pipeline by first...",
    }
)

OVERALL_RESPONSE = json.dumps(
    {
        "overall_score": 80,
        "technical_score": 85,
        "communication_score": 75,
        "practical_experience_score": 78,
        "confidence_score": 76,
        "summary": "Strong technical candidate.",
        "strengths": ["Deep RAG knowledge"],
        "weaknesses": ["Limited deployment detail"],
        "recommendations": ["Practice explaining deployment"],
    }
)


@pytest.mark.asyncio
async def test_single_question_analysis_success():
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.status == AnalysisStatus.COMPLETED
    assert result.overall_score == 80
    assert len(result.questions) == 1
    assert result.questions[0].score == 82
    assert result.questions[0].failed is False
    assert result.questions[0].retrieved_sources[0].filename == "a.pdf"


@pytest.mark.asyncio
async def test_multiple_questions_all_succeed():
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, QUESTION_RESPONSE, QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa("q1"), _qa("q2"), _qa("q3")]))

    assert len(result.questions) == 3
    assert all(not q.failed for q in result.questions)
    assert result.status == AnalysisStatus.COMPLETED


@pytest.mark.asyncio
async def test_malformed_json_response_marks_question_failed_not_whole_analysis():
    provider = ScriptedLLMProvider(["this is not valid json at all", OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.questions[0].failed is True
    assert result.questions[0].error_message is not None
    # Overall analysis still ran despite the question failure.
    assert result.status in (AnalysisStatus.PARTIAL, AnalysisStatus.COMPLETED)


@pytest.mark.asyncio
async def test_missing_required_field_in_response_marks_question_failed():
    incomplete = json.dumps({"assessment": "ok"})  # missing "score"
    provider = ScriptedLLMProvider([incomplete, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.questions[0].failed is True


@pytest.mark.asyncio
async def test_one_failed_question_does_not_lose_other_questions():
    provider = ScriptedLLMProvider(["broken json", QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa("q1"), _qa("q2")]))

    assert len(result.questions) == 2
    assert result.questions[0].failed is True
    assert result.questions[1].failed is False
    assert result.status == AnalysisStatus.PARTIAL


@pytest.mark.asyncio
async def test_llm_provider_exception_marks_question_failed_gracefully():
    provider = ScriptedLLMProvider([RuntimeError("rate limit exceeded"), OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.questions[0].failed is True
    assert "rate limit" in result.questions[0].error_message.lower()


@pytest.mark.asyncio
async def test_empty_question_answers_produces_no_questions_and_no_llm_calls():
    provider = ScriptedLLMProvider([])  # should never be called
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([]))

    assert result.questions == []
    assert result.overall_score == 0
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_question_with_no_retrieved_context_still_analyzes():
    qa = QuestionAnswer(
        question_id="q1", question="Tell me about yourself.", candidate_answer="I am an engineer.",
        timestamp="00:00:05", retrieved_context=[],
    )
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([qa]))

    assert result.questions[0].failed is False
    assert result.questions[0].retrieved_sources == []


@pytest.mark.asyncio
async def test_question_with_empty_answer_still_analyzes():
    qa = QuestionAnswer(
        question_id="q1", question="Explain RAG.", candidate_answer="",
        timestamp="00:00:05", retrieved_context=[],
    )
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([qa]))

    assert result.questions[0].candidate_answer == ""
    assert result.questions[0].failed is False


@pytest.mark.asyncio
async def test_overall_stage_failure_falls_back_to_average_score():
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, "not valid json for overall stage"])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.status == AnalysisStatus.PARTIAL
    assert result.overall_score == 82  # falls back to the single successful question's score
    assert "could not be generated" in result.message.lower()


@pytest.mark.asyncio
async def test_max_questions_to_analyze_truncates_long_interview():
    settings = Settings()
    settings.max_questions_to_analyze = 2
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=settings)
    result = await service.analyze(_request([_qa("q1"), _qa("q2"), _qa("q3"), _qa("q4")]))

    assert len(result.questions) == 2


@pytest.mark.asyncio
async def test_json_wrapped_in_markdown_code_fence_is_parsed():
    fenced = f"```json\n{QUESTION_RESPONSE}\n```"
    provider = ScriptedLLMProvider([fenced, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())
    result = await service.analyze(_request([_qa()]))

    assert result.questions[0].failed is False
    assert result.questions[0].score == 82


@pytest.mark.asyncio
async def test_streaming_yields_progress_events_and_terminal_result():
    provider = ScriptedLLMProvider([QUESTION_RESPONSE, OVERALL_RESPONSE])
    service = AnalysisService(provider=provider, settings=Settings())

    events = []
    async for event in service.stream_analyze(_request([_qa()])):
        events.append(event)

    stages = [e.stage for e in events]
    assert "transcript" in stages
    assert "retrieval" in stages
    assert "question" in stages
    assert "question_complete" in stages
    assert "overall" in stages
    assert stages[-1] == "complete"
    assert events[-1].result is not None
    assert events[-1].result.overall_score == 80

    # No event before "complete" carries a full OverallInterviewAnalysis —
    # only already-validated fragments (question_analysis) or plain text.
    for event in events[:-1]:
        assert event.result is None
