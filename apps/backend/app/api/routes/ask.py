"""Interview Mode's lightweight single-question endpoint (Step 10b).

Kept entirely separate from /api/v1/interviews/analyze — no scoring, no
question/answer extraction, no transcript. Just: one question, its
already-locally-retrieved RAG context, and a plain-text answer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.ask import AskRequest, AskResponse
from app.services.ask_service import get_ask_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    logger.info("[API] POST /api/v1/ask question_len=%d chunks=%d", len(request.question), len(request.retrieved_context))
    service = get_ask_service()
    return await service.ask(request)


@router.post("/stream")
async def ask_stream(request: AskRequest) -> EventSourceResponse:
    logger.info(
        "[API] POST /api/v1/ask/stream question_len=%d chunks=%d",
        len(request.question),
        len(request.retrieved_context),
    )
    service = get_ask_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())
