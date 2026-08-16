"""Service-role Supabase client for backend-only writes (usage_costs, and
any table the desktop client itself must never write directly).

The service-role key bypasses Row Level Security by design, so this client
must never be exposed to the desktop app or any request handler that echoes
its capabilities back to a client. It lives only here.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings

logger = logging.getLogger("app.supabase")


@lru_cache
def get_service_client() -> Client | None:
    """Returns `None` (not an error) if Supabase isn't configured, so local
    dev without a Supabase project still runs — usage-cost writes just no-op.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("Supabase service role not configured; cloud writes are disabled")
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
