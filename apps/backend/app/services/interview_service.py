"""Interview-request-level logic that isn't analysis itself: logging metadata
about an incoming request without ever logging the actual transcript/resume
content (spec: never log secrets, full resume, or full transcript by default).
"""

from __future__ import annotations

import logging

from app.schemas.interview import InterviewAnalysisRequest

logger = logging.getLogger("app.interview")


def log_incoming_request(request: InterviewAnalysisRequest) -> None:
    logger.info("[INTERVIEW] session_id=%s", request.session_id)
    logger.info(
        "[TRANSCRIPT] segments=%d duration=%d",
        len(request.transcript.segments),
        request.transcript.duration_seconds,
    )
    logger.info(
        "[QUESTIONS] count=%d total_retrieved_chunks=%d",
        len(request.question_answers),
        sum(len(qa.retrieved_context) for qa in request.question_answers),
    )
