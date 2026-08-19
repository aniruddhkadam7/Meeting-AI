"""Lightweight product analytics event schema.

Deliberately generic — one event shape for every event name (app_opened,
session_started, agent_created, ai_request, ai_response_latency, ...) rather
than a schema per event type, since the whole point is a small, privacy-
conscious envelope: an event name, a small metadata bag, and nothing that
could be raw audio or document/transcript content. `properties` is validated
for size, not content, since the set of event names is expected to grow.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_EVENT_NAME_LENGTH = 100
MAX_PROPERTIES_KEYS = 20
MAX_PROPERTY_VALUE_LENGTH = 500
MAX_BATCH_SIZE = 50


class AnalyticsEvent(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=MAX_EVENT_NAME_LENGTH)
    properties: Dict[str, Any] = Field(default_factory=dict)
    app_version: Optional[str] = Field(default=None, max_length=50)
    client_timestamp: Optional[str] = None

    @field_validator("properties")
    @classmethod
    def _validate_properties_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if len(value) > MAX_PROPERTIES_KEYS:
            raise ValueError(f"properties may have at most {MAX_PROPERTIES_KEYS} keys")
        for key, val in value.items():
            if isinstance(val, str) and len(val) > MAX_PROPERTY_VALUE_LENGTH:
                raise ValueError(
                    f"properties.{key} exceeds the {MAX_PROPERTY_VALUE_LENGTH}-character limit"
                )
        return value


class AnalyticsEventBatch(BaseModel):
    events: List[AnalyticsEvent] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


class AnalyticsIngestResponse(BaseModel):
    accepted: int
    status: Literal["ok"] = "ok"
