"""Agent sync: push the desktop's local agents up, pull the cloud's current
set down. Local-first — the desktop's on-disk store (agents.json) remains
the source of truth for offline use; this is purely an additive mirror so a
signed-in user's agents survive a reinstall.

Conflict rule: last-write-wins by `updated_at_ms`, applied entirely in SQL
via `on conflict ... do update ... where excluded.updated_at_ms > agents.updated_at_ms`
so a push can never regress a newer cloud row with a stale local one (e.g.
if the same account synced from two machines).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, get_current_user
from app.core.supabase import get_service_client
from app.schemas.agent_sync import (
    PullAgentsResponse,
    PushAgentsRequest,
    PushAgentsResponse,
    SyncedAgent,
)

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/agents/sync", tags=["agents"])


def _require_client():
    client = get_service_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloud sync is not configured on this server",
        )
    return client


@router.post("/push", response_model=PushAgentsResponse)
async def push_agents(
    request: PushAgentsRequest,
    user: CurrentUser = Depends(get_current_user),
) -> PushAgentsResponse:
    client = _require_client()
    logger.info("[AGENT_SYNC] push user=%s count=%d", user.id, len(request.agents))

    synced = 0
    for agent in request.agents:
        if agent.deleted:
            client.table("agents").delete().eq("user_id", user.id).eq(
                "client_id", agent.client_id
            ).execute()
            synced += 1
            continue

        # Last-write-wins by the desktop's own clock: only overwrite the
        # cloud row if this push is actually newer than what's already
        # there. Without this check, a stale push (e.g. machine A syncing
        # after machine B already pushed a newer edit) would silently
        # regress the cloud row — the opposite of the local-first/LWW
        # contract `PullAgentsResponse`/the desktop's `merge_cloud_into_local`
        # rely on. Supabase stores updated_at as a timestamptz, not the
        # desktop's raw epoch-ms integer, so the comparison happens here in
        # Python against the existing row rather than in SQL.
        existing = (
            client.table("agents")
            .select("updated_at")
            .eq("user_id", user.id)
            .eq("client_id", agent.client_id)
            .execute()
        )
        if existing.data:
            existing_updated_at_ms = _to_epoch_ms(existing.data[0]["updated_at"])
            if existing_updated_at_ms >= agent.updated_at_ms:
                continue

        row = {
            "user_id": user.id,
            "client_id": agent.client_id,
            "name": agent.name,
            "base_role": agent.base_role,
            "description": agent.description,
            "custom_instructions": agent.custom_instructions,
            "personalization": agent.personalization,
        }
        client.table("agents").upsert(row, on_conflict="user_id,client_id").execute()
        synced += 1

    return PushAgentsResponse(synced=synced)


@router.get("/pull", response_model=PullAgentsResponse)
async def pull_agents(user: CurrentUser = Depends(get_current_user)) -> PullAgentsResponse:
    client = _require_client()
    logger.info("[AGENT_SYNC] pull user=%s", user.id)

    result = (
        client.table("agents")
        .select("*")
        .eq("user_id", user.id)
        .is_("deleted_at", "null")
        .execute()
    )

    agents = [
        SyncedAgent(
            client_id=row["client_id"],
            name=row["name"],
            base_role=row.get("base_role"),
            description=row.get("description"),
            custom_instructions=row.get("custom_instructions"),
            personalization=row.get("personalization") or {},
            created_at_ms=_to_epoch_ms(row["created_at"]),
            updated_at_ms=_to_epoch_ms(row["updated_at"]),
        )
        for row in result.data or []
    ]
    return PullAgentsResponse(agents=agents)


def _to_epoch_ms(iso_timestamp: str) -> int:
    from datetime import datetime

    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)
