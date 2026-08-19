"""Security regression tests for the unauthenticated LLM-route rate limiter
(app/core/rate_limit.py). These endpoints require no auth by design (see
app/api/routes/ask.py etc.), so a per-IP request cap is the only thing
bounding anonymous OpenAI/Anthropic spend."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.rate_limit import SlidingWindowRateLimiter
from app.main import app

client = TestClient(app)


def _ask_payload():
    return {
        "question": "What is your experience with Python?",
        "retrieved_context": [],
        "candidate_context": None,
    }


def test_sliding_window_limiter_blocks_after_max_requests():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("client-a")  # must not raise

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("client-a")
    assert exc_info.value.status_code == 429


def test_sliding_window_limiter_tracks_clients_independently():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    limiter.check("client-a")  # must not raise
    limiter.check("client-b")  # different key, independent budget — must not raise


def test_sliding_window_limiter_expires_old_hits():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    limiter.check("client-a")

    import time

    from fastapi import HTTPException

    # Simulate the window having elapsed by rewriting the recorded hit
    # timestamp into the past, rather than sleeping 60s in a unit test.
    limiter._hits["client-a"][0] -= 61.0
    limiter.check("client-a")  # must not raise — old hit has expired out


def test_unauthenticated_ask_endpoint_is_rate_limited_per_client(monkeypatch):
    """End-to-end: enough rapid requests to /api/v1/ask (no auth required)
    from the same client must eventually return 429, not silently allow
    unbounded LLM spend."""
    from app.core.rate_limit import llm_rate_limiter

    monkeypatch.setattr(llm_rate_limiter, "_max_requests", 3)

    statuses = [client.post("/api/v1/ask", json=_ask_payload()).status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


def test_health_endpoint_is_not_rate_limited(monkeypatch):
    """The rate limit is scoped to the LLM-backed v1 routers only (see
    app/api/router.py) — /health must stay reachable regardless."""
    from app.core.rate_limit import llm_rate_limiter

    monkeypatch.setattr(llm_rate_limiter, "_max_requests", 1)
    client.post("/api/v1/ask", json=_ask_payload())  # consume the budget

    for _ in range(5):
        assert client.get("/health").status_code == 200
