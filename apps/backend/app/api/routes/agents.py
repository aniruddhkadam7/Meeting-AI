"""Custom Agents: one generic live-ask endpoint shared by every predefined
role and every fully custom agent (see app/services/agent_prompt_builder.py
for how agent_id/base_role/description/custom_instructions/personalization
become a system prompt)."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.schemas.agent_ask import AgentAskRequest, AgentAskResponse
from app.services.agent_ask_service import get_agent_ask_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/ask", response_model=AgentAskResponse)
async def ask(request: AgentAskRequest) -> AgentAskResponse:
    logger.info(
        "[API] POST /api/v1/agents/ask agent_id=%s question_len=%d",
        request.agent_id, len(request.question),
    )
    service = get_agent_ask_service()
    return await service.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: AgentAskRequest) -> EventSourceResponse:
    logger.info(
        "[API] POST /api/v1/agents/ask/stream agent_id=%s question_len=%d",
        request.agent_id, len(request.question),
    )
    service = get_agent_ask_service()

    async def event_generator():
        async for delta in service.ask_stream(request):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())
