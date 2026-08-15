"""Consulting Mode endpoints: live ask flow + end-of-session structured notes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.consulting import (
    ConsultingAskRequest,
    ConsultingAskResponse,
    ConsultingNote,
    ConsultingSummaryRequest,
)
from app.services.consulting_service import get_consulting_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/consulting", tags=["consulting"])


@router.post("/ask", response_model=ConsultingAskResponse)
async def ask(request: ConsultingAskRequest) -> ConsultingAskResponse:
    logger.info("[API] POST /api/v1/consulting/ask question_len=%d", len(request.question))
    service = get_consulting_service()
    return await service.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: ConsultingAskRequest) -> EventSourceResponse:
    logger.info("[API] POST /api/v1/consulting/ask/stream question_len=%d", len(request.question))
    service = get_consulting_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())


@router.post("/summarize", response_model=ConsultingNote)
async def summarize(request: ConsultingSummaryRequest) -> ConsultingNote:
    logger.info("[API] POST /api/v1/consulting/summarize turns=%d", len(request.turns))
    service = get_consulting_service()
    return await service.summarize(request)
