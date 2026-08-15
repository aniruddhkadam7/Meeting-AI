"""Backend configuration, sourced from environment variables / .env.

Kept intentionally minimal for Phase 1: no auth, no multi-tenancy, no cloud
config.
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
