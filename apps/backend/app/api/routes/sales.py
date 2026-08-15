"""Sales Mode endpoints: live ask flow + end-of-call summary."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.sales import SalesAskRequest, SalesAskResponse, SalesCallSummary, SalesSummaryRequest
from app.services.sales_service import get_sales_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("/ask", response_model=SalesAskResponse)
async def ask(request: SalesAskRequest) -> SalesAskResponse:
    logger.info("[API] POST /api/v1/sales/ask question_len=%d", len(request.question))
    service = get_sales_service()
    return await service.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: SalesAskRequest) -> EventSourceResponse:
    logger.info("[API] POST /api/v1/sales/ask/stream question_len=%d", len(request.question))
    service = get_sales_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())


@router.post("/summarize", response_model=SalesCallSummary)
async def summarize(request: SalesSummaryRequest) -> SalesCallSummary:
    logger.info("[API] POST /api/v1/sales/summarize turns=%d", len(request.turns))
    service = get_sales_service()
    return await service.summarize(request)
