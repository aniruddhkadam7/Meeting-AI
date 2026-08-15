import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.analysis import OverallInterviewAnalysis
from app.schemas.interview import InterviewAnalysisRequest
from app.services.analysis_service import get_analysis_service
from app.services.interview_service import log_incoming_request

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("/analyze", response_model=OverallInterviewAnalysis)
async def analyze_interview(request: InterviewAnalysisRequest) -> OverallInterviewAnalysis:
    """Non-streaming analysis — kept for simple callers/tests. The desktop app
    uses the streaming endpoint below so the UI can show progress instead of
    blocking on a potentially multi-question, multi-LLM-call analysis."""
    logger.info("[API] POST /api/v1/interviews/analyze")
    log_incoming_request(request)

    service = get_analysis_service()
    return await service.analyze(request)


@router.post("/analyze/stream")
async def analyze_interview_stream(request: InterviewAnalysisRequest) -> EventSourceResponse:
    """Server-Sent Events stream of analysis progress. Each event's `data` is
    a JSON object `{ stage, detail, question_analysis?, result? }` — see
    AnalysisProgressEvent. The final event (`stage: "complete"`) carries the
    full validated `OverallInterviewAnalysis` in `result`; no earlier event
    ever contains raw/unvalidated model output.
    """
    logger.info("[API] POST /api/v1/interviews/analyze/stream")
    log_incoming_request(request)

    service = get_analysis_service()

    async def event_generator():
        async for event in service.stream_analyze(request):
            yield {"event": event.stage, "data": event.to_sse_data()}

    return EventSourceResponse(event_generator())
