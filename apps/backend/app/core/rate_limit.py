"""Minimal in-process rate limiting for the unauthenticated LLM-backed routes.

These endpoints (interviews/ask/setup/sales/consulting/notes/agents — see
app/main.py) accept no auth by design (spec: stateless LLM pass-throughs) but
that means any caller who can reach this process can drive arbitrary
OpenAI/Anthropic spend with no per-caller limit at all. A full distributed
limiter (Redis, etc.) would be new infrastructure this deployment doesn't
have; a single-process in-memory sliding window is the smallest mechanism
that closes the "unbounded anonymous spend" gap for the common single-instance
deployment this backend actually runs as (see fly.toml).

Not a substitute for an API gateway/WAF-level limiter in a multi-instance
deployment — flagged in the security report as the production caveat.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window_seconds:
                hits.popleft()
            if len(hits) >= self._max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests, please slow down.",
                )
            hits.append(now)


# 30 requests/minute per client IP across all LLM-backed routes combined —
# generous for a single interactive user (these are user-initiated, not
# polled), tight enough to bound anonymous credit-burning abuse.
llm_rate_limiter = SlidingWindowRateLimiter(max_requests=30, window_seconds=60.0)


def _client_key(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def enforce_llm_rate_limit(request: Request) -> None:
    llm_rate_limiter.check(_client_key(request))
