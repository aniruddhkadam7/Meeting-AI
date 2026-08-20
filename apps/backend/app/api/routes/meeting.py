"""Meeting Mode endpoints: live ask flow + end-of-meeting summary."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.meeting import MeetingAskRequest, MeetingAskResponse, MeetingSummary, MeetingSummaryRequest
from app.services.meeting_service import get_meeting_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/meeting", tags=["meeting"])


@router.post("/ask", response_model=MeetingAskResponse)
async def ask(request: MeetingAskRequest) -> MeetingAskResponse:
    logger.info("[API] POST /api/v1/meeting/ask question_len=%d", len(request.question))
    service = get_meeting_service()
    return await service.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: MeetingAskRequest) -> EventSourceResponse:
    logger.info("[API] POST /api/v1/meeting/ask/stream question_len=%d", len(request.question))
    service = get_meeting_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())


@router.post("/summarize", response_model=MeetingSummary)
async def summarize(request: MeetingSummaryRequest) -> MeetingSummary:
    logger.info("[API] POST /api/v1/meeting/summarize turns=%d", len(request.turns))
    service = get_meeting_service()
    return await service.summarize(request)
