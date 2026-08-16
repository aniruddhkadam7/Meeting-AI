"""Schemas for syncing the desktop's local Agent store to REDLY Cloud.

Mirrors `apps/desktop/src-tauri/src/agents/model.rs::Agent` field-for-field.
`client_id` is that struct's own `id` (e.g. "agent-<hex>-<hex>") — the cloud
row gets its own uuid `id`, but sync always matches on `(user_id, client_id)`
so the desktop never needs to learn or store a second id.

Sync is last-write-wins by `updated_at_ms`: whichever side has the newer
timestamp for a given client_id wins on pull; on push, the desktop simply
upserts its current local state (it's the one that just changed it).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2_000
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 4_000


class SyncedAgent(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    base_role: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    custom_instructions: Optional[str] = Field(default=None, max_length=MAX_CUSTOM_INSTRUCTIONS_LENGTH)
    personalization: Dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int
    updated_at_ms: int
    deleted: bool = False


class PushAgentsRequest(BaseModel):
    agents: List[SyncedAgent] = Field(..., max_length=500)


class PushAgentsResponse(BaseModel):
    synced: int


class PullAgentsResponse(BaseModel):
    agents: List[SyncedAgent]
