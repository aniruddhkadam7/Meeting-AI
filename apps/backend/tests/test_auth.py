"""Tests for Supabase JWT verification (app/core/auth.py) and the
auth-gated routes (analytics ingest, agent sync)."""

from __future__ import annotations

import jwt
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Must match tests/conftest.py's SUPABASE_JWT_SECRET, set before app.main
# (and app.core.config) is first imported.
TEST_SECRET = "test-jwt-secret-for-unit-tests-only"


def _make_token(*, user_id: str = "user-123", email: str = "u@example.com", expired: bool = False) -> str:
    import time

    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": now - 10 if expired else now + 3600,
        "iat": now,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def test_analytics_rejects_missing_token():
    response = client.post("/api/v1/analytics/events", json={"events": [{"event_name": "app_opened"}]})
    assert response.status_code == 401


def test_analytics_rejects_invalid_token():
    response = client.post(
        "/api/v1/analytics/events",
        json={"events": [{"event_name": "app_opened"}]},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_analytics_rejects_expired_token():
    token = _make_token(expired=True)
    response = client.post(
        "/api/v1/analytics/events",
        json={"events": [{"event_name": "app_opened"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_analytics_accepts_valid_token_and_no_op_writes_without_supabase_configured():
    token = _make_token()
    response = client.post(
        "/api/v1/analytics/events",
        json={"events": [{"event_name": "app_opened"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Supabase isn't configured in this test env, so writes no-op — the
    # important assertion is that auth passed (not a 401/403).
    assert response.status_code == 200
    assert response.json()["accepted"] == 0


def test_agent_sync_pull_requires_auth():
    response = client.get("/api/v1/agents/sync/pull")
    assert response.status_code == 401


def test_agent_sync_pull_returns_503_without_supabase_configured():
    token = _make_token()
    response = client.get(
        "/api/v1/agents/sync/pull",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
