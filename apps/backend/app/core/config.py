"""Backend configuration, sourced from environment variables / .env.

Smallbird Cloud (hybrid architecture): this service now also verifies Supabase
Auth JWTs and writes usage/cost tracking to Supabase Postgres via the
service-role key. Both are optional at the config level — an unset
`SUPABASE_*` block means auth-required routes reject with a clear 401 (server
misconfigured) and usage-cost writes silently no-op, so local dev without a
Supabase project still runs the rest of the API (mock LLM, existing ask
routes) unchanged.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Loads apps/backend/.env into the process environment before any Settings
# field reads os.getenv(). Safe to call even if the file doesn't exist (pure
# no-op) — never overrides variables already set in the real environment.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings:
    host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    port: int = int(os.getenv("BACKEND_PORT", "8000"))

    # "production" disables the interactive /docs, /redoc, and /openapi.json
    # routes (see app/main.py) — those expose the full route/schema surface to
    # anyone who can reach the server and aren't needed once the API is fixed.
    # Any other value (including unset, the local-dev default) leaves them on.
    environment: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    # Origins the desktop app's WebView may call from during development. Tauri's
    # dev server runs on localhost:1420; the packaged app's WebView uses a
    # tauri://localhost-style origin. Kept as an explicit allowlist rather than "*"
    # per the CORS requirement (no unrestricted CORS, even in dev).
    cors_allow_origins: List[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:1420,http://127.0.0.1:1420,tauri://localhost,https://tauri.localhost",
        ).split(",")
        if origin.strip()
    ]

    # LLMProvider selection. "mock" requires no API key and is used whenever
    # LLM_PROVIDER is unset/unrecognized or the relevant API key is missing —
    # see services/llm/__init__.py::get_llm_provider.
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY") or None
    anthropic_api_key: Optional[str] = os.getenv("ANTHROPIC_API_KEY") or None

    # Cost/context controls (spec section 28).
    max_questions_to_analyze: int = int(os.getenv("MAX_QUESTIONS_TO_ANALYZE", "50"))
    top_k_retrieval: int = int(os.getenv("TOP_K_RETRIEVAL", "5"))
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
    max_output_tokens: int = int(os.getenv("MAX_OUTPUT_TOKENS", "1500"))

    # Interview Mode's single-question "ask" flow — deliberately much smaller
    # than the full analysis output budget above, since the answer needs to be
    # readable at a glance during a live interview.
    max_answer_tokens: int = int(os.getenv("MAX_ANSWER_TOKENS", "250"))

    # Interview Mode answers on its own model, independent of the analysis
    # pipeline's LLM_MODEL: this call sits in the middle of a live
    # conversation, so a fast, inexpensive model is the right default even if
    # the (offline, once-per-interview) analysis pipeline uses a stronger one.
    # Falls back to llm_model when ASK_LLM_MODEL is unset.
    ask_model: str = os.getenv("ASK_LLM_MODEL") or os.getenv("LLM_MODEL", "gpt-4o-mini")

    # Warmer than the analysis pipeline's 0.2: a live spoken answer reading as
    # natural matters more here than determinism. Raised from 0.4 — at 0.4 the
    # model reliably picked the single most "polished/report" phrasing for a
    # given sentence even with explicit conversational wording in the system
    # prompt (e.g. "ensuring they're stored in a way that makes them easy to
    # access" instead of "so I can grab them later"); loosening the sampling
    # gives it room to actually land on the looser phrasing the prompt asks
    # for, at the cost of very slightly more variance answer-to-answer, which
    # is an acceptable trade for a live interview candidate voice.
    ask_temperature: float = float(os.getenv("ASK_TEMPERATURE", "0.65"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Smallbird Cloud: Supabase Auth + Postgres ---------------------------
    # Project URL and anon key are the same values the desktop app is given
    # (safe to be non-secret; RLS is what actually protects data). The JWT
    # secret and service-role key are backend-only and must never be sent to
    # a client.
    supabase_url: Optional[str] = os.getenv("SUPABASE_URL") or None
    supabase_anon_key: Optional[str] = os.getenv("SUPABASE_ANON_KEY") or None
    supabase_jwt_secret: Optional[str] = os.getenv("SUPABASE_JWT_SECRET") or None
    supabase_service_role_key: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None

    # Rough per-1K-token USD pricing used only to populate usage_costs'
    # estimated_cost_usd for cost visibility — not billing-accurate, not used
    # for enforcement (no subscription/usage enforcement exists yet).
    price_per_1k_input_usd: float = float(os.getenv("PRICE_PER_1K_INPUT_USD", "0.00015"))
    price_per_1k_output_usd: float = float(os.getenv("PRICE_PER_1K_OUTPUT_USD", "0.0006"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
