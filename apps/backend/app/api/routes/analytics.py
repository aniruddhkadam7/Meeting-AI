"""Product analytics ingestion.

Write-only from the desktop app's perspective: it posts a small batch of
events (app_opened, session_started, agent_created, ai_request,
ai_response_latency, feature_usage, error, ...) tied to the signed-in user.
Never accepts raw audio, document content, or full transcript/message text —
that's enforced by the caller (desktop app) choosing what goes in
`properties`, not by this endpoint, but the schema's size caps make bulk
content dumping impractical.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.supabase import get_service_client
from app.schemas.analytics import AnalyticsEventBatch, AnalyticsIngestResponse

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/events", response_model=AnalyticsIngestResponse)
async def ingest_events(
    batch: AnalyticsEventBatch,
    user: CurrentUser = Depends(get_current_user),
) -> AnalyticsIngestResponse:
    logger.info("[ANALYTICS] user=%s events=%d", user.id, len(batch.events))

    client = get_service_client()
    if client is None:
        # Supabase not configured (local dev) — accept-and-drop rather than
        # error, so analytics never blocks the desktop app from working.
        return AnalyticsIngestResponse(accepted=0)

    rows = [
        {
            "user_id": user.id,
            "event_name": event.event_name,
            "properties": event.properties,
            "app_version": event.app_version,
        }
        for event in batch.events
    ]
    try:
        client.table("usage_events").insert(rows).execute()
    except Exception:  # noqa: BLE001 — analytics must never fail the caller
        logger.exception("[ANALYTICS] failed to write usage_events batch")
        return AnalyticsIngestResponse(accepted=0)

    return AnalyticsIngestResponse(accepted=len(rows))
