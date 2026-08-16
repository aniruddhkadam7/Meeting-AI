"""Usage/cost tracking: writes one row to `usage_costs` per LLM call, via the
Supabase service-role client. Fire-and-forget from the caller's perspective —
a Supabase outage must never fail or slow down an interview/agent answer, so
every failure here is logged and swallowed, never raised.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.supabase import get_service_client

logger = logging.getLogger("app.usage")


def record_llm_usage(
    *,
    user_id: str | None,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    request_kind: str,
) -> None:
    if user_id is None:
        return
    client = get_service_client()
    if client is None:
        return

    settings = get_settings()
    estimated_cost = (
        (input_tokens / 1000) * settings.price_per_1k_input_usd
        + (output_tokens / 1000) * settings.price_per_1k_output_usd
    )

    try:
        client.table("usage_costs").insert(
            {
                "user_id": user_id,
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": round(estimated_cost, 6),
                "request_kind": request_kind,
            }
        ).execute()
    except Exception:  # noqa: BLE001 — never let analytics break a real request
        logger.exception("[USAGE] failed to record LLM usage cost row")
