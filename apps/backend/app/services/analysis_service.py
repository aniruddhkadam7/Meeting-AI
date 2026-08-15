"""Two-stage LLM-powered interview analysis (spec section 26).

    Stage 1 (per question): question + answer + retrieved RAG context -> LLM -> QuestionAnalysis
    Stage 2 (aggregate):    all QuestionAnalysis + role/company/JD -> LLM -> OverallInterviewAnalysis

If a question's Stage-1 call fails or returns invalid structured output, that
question is marked `failed=True` with an error message and the pipeline
continues with the rest — one bad question never loses the whole analysis
(spec section 30). If every question fails, Stage 2 still runs and produces a
best-effort (likely low-confidence) overall summary noting the failures.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, List, Optional

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.analysis import (
    AnalysisStatus,
    OverallInterviewAnalysis,
    QuestionAnalysis,
    RetrievedSourceRef,
)
from app.schemas.interview import InterviewAnalysisRequest, QuestionAnswer
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider
from app.services.prompt_builder import build_overall_prompt, build_question_prompt

logger = logging.getLogger("app.analysis")


class AnalysisProgressEvent:
    """Emitted during streaming analysis so the desktop UI can show
    incremental progress without rendering raw partial JSON (spec section 16).
    `stage="complete"` carries the final, fully-validated
    `OverallInterviewAnalysis` in `result` — that is the only point at which a
    complete structured object is sent; every earlier event carries only
    already-validated fragments (a single `QuestionAnalysis`) or plain status
    text, never raw/partial JSON.
    """

    def __init__(
        self,
        stage: str,
        detail: str,
        question_analysis: Optional[QuestionAnalysis] = None,
        result: Optional[OverallInterviewAnalysis] = None,
    ) -> None:
        self.stage = stage
        self.detail = detail
        self.question_analysis = question_analysis
        self.result = result

    def to_sse_data(self) -> str:
        payload: dict = {"stage": self.stage, "detail": self.detail}
        if self.question_analysis is not None:
            payload["question_analysis"] = self.question_analysis.model_dump()
        if self.result is not None:
            payload["result"] = self.result.model_dump()
        return json.dumps(payload)


def _extract_json_object(text: str) -> dict:
    """LLMs occasionally wrap JSON in prose or code fences despite
    instructions; this extracts the first well-formed top-level JSON object
    rather than assuming `text` is pure JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start : end + 1])


class AnalysisService:
    def __init__(self, provider: Optional[LLMProvider] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or get_llm_provider(self._settings)

    async def _analyze_question(self, qa: QuestionAnswer, request: InterviewAnalysisRequest) -> QuestionAnalysis:
        system_prompt, user_prompt = build_question_prompt(
            qa, request.role, request.company, request.job_description
        )
        try:
            raw = await self._provider.generate(
                [LLMMessage("system", system_prompt), LLMMessage("user", user_prompt)],
                temperature=0.2,
                max_tokens=self._settings.max_output_tokens,
            )
            parsed = _extract_json_object(raw)
            return QuestionAnalysis(
                question_id=qa.question_id,
                question=qa.question,
                candidate_answer=qa.candidate_answer,
                assessment=parsed["assessment"],
                score=int(parsed["score"]),
                strengths=list(parsed.get("strengths", [])),
                issues=list(parsed.get("issues", [])),
                improved_answer=parsed.get("improved_answer", ""),
                retrieved_sources=[
                    RetrievedSourceRef(
                        filename=c.source_filename,
                        document_type=c.document_type,
                        score=c.score,
                        text=c.text,
                    )
                    for c in qa.retrieved_context
                ],
                failed=False,
            )
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[ANALYSIS] question analysis failed question_id=%s error=%s", qa.question_id, exc)
            return QuestionAnalysis(
                question_id=qa.question_id,
                question=qa.question,
                candidate_answer=qa.candidate_answer,
                assessment="",
                score=0,
                retrieved_sources=[
                    RetrievedSourceRef(
                        filename=c.source_filename, document_type=c.document_type, score=c.score, text=c.text
                    )
                    for c in qa.retrieved_context
                ],
                failed=True,
                error_message=str(exc),
            )
        except Exception as exc:  # provider-level failures: rate limit, auth, timeout, etc.
            logger.error("[ANALYSIS] LLM call failed question_id=%s error=%s", qa.question_id, exc)
            return QuestionAnalysis(
                question_id=qa.question_id,
                question=qa.question,
                candidate_answer=qa.candidate_answer,
                assessment="",
                score=0,
                failed=True,
                error_message=f"LLM request failed: {exc}",
            )

    async def _analyze_overall(
        self, question_analyses: List[QuestionAnalysis], request: InterviewAnalysisRequest
    ) -> dict:
        system_prompt, user_prompt = build_overall_prompt(
            question_analyses, request.role, request.company, request.job_description
        )
        raw = await self._provider.generate(
            [LLMMessage("system", system_prompt), LLMMessage("user", user_prompt)],
            temperature=0.2,
            max_tokens=self._settings.max_output_tokens,
        )
        return _extract_json_object(raw)

    async def analyze(self, request: InterviewAnalysisRequest) -> OverallInterviewAnalysis:
        """Non-streaming path: runs both stages and returns the final result.
        Used by the non-streaming /analyze endpoint kept for compatibility.
        """
        question_analyses: List[QuestionAnalysis] = []
        questions_to_analyze = request.question_answers[: self._settings.max_questions_to_analyze]
        for qa in questions_to_analyze:
            question_analyses.append(await self._analyze_question(qa, request))

        return await self._finalize(question_analyses, request)

    async def stream_analyze(self, request: InterviewAnalysisRequest) -> AsyncIterator[AnalysisProgressEvent]:
        """Streaming path: yields progress events as each stage completes,
        finishing with a `complete` event carrying the full validated
        `OverallInterviewAnalysis`. Never yields raw/partial JSON — each
        question's result is only emitted once it has been fully parsed and
        validated against `QuestionAnalysis` (spec section 16)."""

        yield AnalysisProgressEvent("transcript", "Processing transcript...")

        questions_to_analyze = request.question_answers[: self._settings.max_questions_to_analyze]
        if len(request.question_answers) > self._settings.max_questions_to_analyze:
            logger.info(
                "[ANALYSIS] truncating question count %d -> %d (MAX_QUESTIONS_TO_ANALYZE)",
                len(request.question_answers),
                self._settings.max_questions_to_analyze,
            )

        yield AnalysisProgressEvent("retrieval", f"Retrieved context for {len(questions_to_analyze)} questions.")

        question_analyses: List[QuestionAnalysis] = []
        for i, qa in enumerate(questions_to_analyze):
            yield AnalysisProgressEvent(
                "question", f"Analyzing question {i + 1} of {len(questions_to_analyze)}..."
            )
            analysis = await self._analyze_question(qa, request)
            question_analyses.append(analysis)
            yield AnalysisProgressEvent(
                "question_complete", f"Completed question {i + 1} of {len(questions_to_analyze)}.", analysis
            )

        yield AnalysisProgressEvent("overall", "Generating overall assessment...")
        result = await self._finalize(question_analyses, request)

        yield AnalysisProgressEvent("complete", "Analysis complete.", result=result)

    async def _finalize(
        self, question_analyses: List[QuestionAnalysis], request: InterviewAnalysisRequest
    ) -> OverallInterviewAnalysis:
        logger.info(
            "[ANALYSIS] stage1 complete session_id=%s questions=%d failed=%d",
            request.session_id,
            len(question_analyses),
            sum(1 for q in question_analyses if q.failed),
        )

        if not question_analyses:
            return OverallInterviewAnalysis(
                session_id=request.session_id,
                status=AnalysisStatus.COMPLETED,
                overall_score=0,
                technical_score=0,
                communication_score=0,
                practical_experience_score=0,
                confidence_score=0,
                summary="No interview questions were identified in the transcript, so no analysis could be generated.",
                questions=[],
                message="No question/answer pairs were extracted from the transcript.",
            )

        try:
            overall_raw = await self._analyze_overall(question_analyses, request)
            status = (
                AnalysisStatus.PARTIAL
                if any(q.failed for q in question_analyses)
                else AnalysisStatus.COMPLETED
            )
            return OverallInterviewAnalysis(
                session_id=request.session_id,
                status=status,
                overall_score=int(overall_raw["overall_score"]),
                technical_score=int(overall_raw["technical_score"]),
                communication_score=int(overall_raw["communication_score"]),
                practical_experience_score=int(overall_raw["practical_experience_score"]),
                confidence_score=int(overall_raw["confidence_score"]),
                summary=overall_raw.get("summary", ""),
                strengths=list(overall_raw.get("strengths", [])),
                weaknesses=list(overall_raw.get("weaknesses", [])),
                recommendations=list(overall_raw.get("recommendations", [])),
                questions=question_analyses,
                message="",
            )
        except Exception as exc:
            logger.error("[ANALYSIS] overall analysis failed session_id=%s error=%s", request.session_id, exc)
            successful = [q for q in question_analyses if not q.failed]
            avg_score = int(sum(q.score for q in successful) / len(successful)) if successful else 0
            return OverallInterviewAnalysis(
                session_id=request.session_id,
                status=AnalysisStatus.PARTIAL,
                overall_score=avg_score,
                technical_score=avg_score,
                communication_score=avg_score,
                practical_experience_score=avg_score,
                confidence_score=avg_score,
                summary="",
                questions=question_analyses,
                message=f"Overall analysis could not be generated ({exc}); showing per-question results with an approximate average score.",
            )


def get_analysis_service() -> AnalysisService:
    return AnalysisService()
