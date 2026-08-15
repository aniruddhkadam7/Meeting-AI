"""Notes Mode endpoints: summarize a note, and ask AI a question using notes
as optional context."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.notes import NoteSummary, NotesAskRequest, NotesAskResponse, NotesSummaryRequest
from app.services.notes_service import get_notes_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("/summarize", response_model=NoteSummary)
async def summarize(request: NotesSummaryRequest) -> NoteSummary:
    logger.info("[API] POST /api/v1/notes/summarize body_len=%d", len(request.body))
    service = get_notes_service()
    return await service.summarize(request)


@router.post("/ask", response_model=NotesAskResponse)
async def ask(request: NotesAskRequest) -> NotesAskResponse:
    logger.info("[API] POST /api/v1/notes/ask question_len=%d notes=%d", len(request.question), len(request.notes))
    service = get_notes_service()
    return await service.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: NotesAskRequest) -> EventSourceResponse:
    logger.info("[API] POST /api/v1/notes/ask/stream question_len=%d", len(request.question))
    service = get_notes_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())
