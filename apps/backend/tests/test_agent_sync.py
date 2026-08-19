"""Tests for agent sync push/pull (app/api/routes/agent_sync.py), focused on
the last-write-wins conflict rule on push — a real bug was found where the
push handler queried the existing row's timestamp but never used it, letting
a stale push silently overwrite a newer cloud row. Uses a minimal in-memory
fake standing in for the Supabase client (this project's `supabase` package
has no official test double, and a real Supabase project shouldn't be
required to exercise this business logic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TEST_SECRET = "test-jwt-secret-for-unit-tests-only"


def _make_token(user_id: str = "user-123") -> str:
    import time

    now = int(time.time())
    payload = {"sub": user_id, "email": "u@example.com", "aud": "authenticated", "exp": now + 3600, "iat": now}
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    """Chainable stand-in for postgrest's query builder, just enough surface
    for agent_sync.py: select/eq/is_/execute, insert/upsert/delete/execute."""

    def __init__(self, table: "_FakeTable", op: str, payload=None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: dict[str, object] = {}

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def is_(self, column, value):
        self._filters[column] = None if value == "null" else value
        return self

    def select(self, *_args):
        return self

    def execute(self):
        rows = self._table.rows
        if self._op == "select":
            matched = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
            return _FakeResult(matched)
        if self._op == "delete":
            before = len(rows)
            rows[:] = [r for r in rows if not all(r.get(k) == v for k, v in self._filters.items())]
            return _FakeResult([{} for _ in range(before - len(rows))])
        if self._op == "upsert":
            key = (self._payload["user_id"], self._payload["client_id"])
            for r in rows:
                if (r["user_id"], r["client_id"]) == key:
                    r.update(self._payload)
                    r["updated_at"] = datetime.now(timezone.utc).isoformat()
                    return _FakeResult([r])
            new_row = dict(self._payload)
            new_row["updated_at"] = datetime.now(timezone.utc).isoformat()
            new_row["created_at"] = new_row["updated_at"]
            new_row["deleted_at"] = None
            rows.append(new_row)
            return _FakeResult([new_row])
        if self._op == "insert":
            rows.extend(self._payload if isinstance(self._payload, list) else [self._payload])
            return _FakeResult(rows)
        raise NotImplementedError(self._op)


class _FakeTable:
    def __init__(self):
        self.rows: list[dict] = []

    def select(self, *_args):
        return _FakeTableQuery(self, "select")

    def upsert(self, payload, on_conflict=None):  # noqa: ARG002 - signature match only
        return _FakeTableQuery(self, "upsert", payload)

    def delete(self):
        return _FakeTableQuery(self, "delete")

    def insert(self, payload):
        return _FakeTableQuery(self, "insert", payload)


class FakeSupabaseClient:
    def __init__(self):
        self._tables: dict[str, _FakeTable] = {}

    def table(self, name: str) -> _FakeTable:
        return self._tables.setdefault(name, _FakeTable())

    def seed_agent(self, *, user_id: str, client_id: str, name: str, updated_at_ms: int):
        updated_at = datetime.fromtimestamp(updated_at_ms / 1000, tz=timezone.utc).isoformat()
        self.table("agents").rows.append(
            {
                "user_id": user_id,
                "client_id": client_id,
                "name": name,
                "base_role": None,
                "description": None,
                "custom_instructions": None,
                "personalization": {},
                "created_at": updated_at,
                "updated_at": updated_at,
                "deleted_at": None,
            }
        )


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    yield


def _patch_client(monkeypatch, fake_client):
    import app.api.routes.agent_sync as agent_sync_module

    monkeypatch.setattr(agent_sync_module, "get_service_client", lambda: fake_client)


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_push_rejects_stale_write_over_newer_cloud_row(monkeypatch):
    fake = FakeSupabaseClient()
    now = datetime.now(timezone.utc)
    fake.seed_agent(user_id="user-123", client_id="agent-1", name="Newer Cloud Name", updated_at_ms=_epoch_ms(now))
    _patch_client(monkeypatch, fake)

    token = _make_token()
    stale_updated_at_ms = _epoch_ms(now - timedelta(hours=1))
    response = client.post(
        "/api/v1/agents/sync/push",
        json={
            "agents": [
                {
                    "client_id": "agent-1",
                    "name": "Stale Local Name",
                    "created_at_ms": stale_updated_at_ms,
                    "updated_at_ms": stale_updated_at_ms,
                }
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    # The cloud row must NOT have been overwritten by the stale push.
    row = fake.table("agents").rows[0]
    assert row["name"] == "Newer Cloud Name"


def test_push_accepts_newer_write_over_older_cloud_row(monkeypatch):
    fake = FakeSupabaseClient()
    now = datetime.now(timezone.utc)
    fake.seed_agent(user_id="user-123", client_id="agent-1", name="Old Cloud Name", updated_at_ms=_epoch_ms(now - timedelta(hours=1)))
    _patch_client(monkeypatch, fake)

    token = _make_token()
    newer_updated_at_ms = _epoch_ms(now)
    response = client.post(
        "/api/v1/agents/sync/push",
        json={
            "agents": [
                {
                    "client_id": "agent-1",
                    "name": "Newer Local Name",
                    "created_at_ms": newer_updated_at_ms,
                    "updated_at_ms": newer_updated_at_ms,
                }
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    row = fake.table("agents").rows[0]
    assert row["name"] == "Newer Local Name"


def test_push_creates_a_new_row_when_none_exists(monkeypatch):
    fake = FakeSupabaseClient()
    _patch_client(monkeypatch, fake)

    token = _make_token()
    response = client.post(
        "/api/v1/agents/sync/push",
        json={"agents": [{"client_id": "agent-1", "name": "Brand New Agent", "created_at_ms": 1000, "updated_at_ms": 1000}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["synced"] == 1
    assert len(fake.table("agents").rows) == 1


def test_pull_never_returns_another_users_agents(monkeypatch):
    """Defense-in-depth guard alongside RLS: even though Postgres RLS is what
    actually enforces per-user isolation against the real database, this
    confirms the backend's own query never asks for anything but the
    caller's own user_id — the .eq("user_id", user.id) filter isn't
    accidentally dropped or short-circuited. Row Level Security is verified
    separately at the SQL level (supabase/migrations/0001_init.sql); this
    is what's testable without a live Supabase project."""
    fake = FakeSupabaseClient()
    fake.seed_agent(user_id="user-A", client_id="agent-a1", name="User A's Agent", updated_at_ms=1000)
    fake.seed_agent(user_id="user-B", client_id="agent-b1", name="User B's Agent", updated_at_ms=1000)
    _patch_client(monkeypatch, fake)

    token_for_user_a = _make_token(user_id="user-A")
    response = client.get(
        "/api/v1/agents/sync/pull",
        headers={"Authorization": f"Bearer {token_for_user_a}"},
    )

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["client_id"] == "agent-a1"
    assert all(a["client_id"] != "agent-b1" for a in agents)


def test_push_cannot_overwrite_another_users_agent_row(monkeypatch):
    """Even if two users' agents happened to share a client_id (e.g. two
    different desktop installs both picking the same locally-generated id
    — not expected in practice since ids are randomized, but not
    impossible), a push must never let user B's request touch user A's
    row. The push handler's queries are always scoped by both user_id and
    client_id, so this exercises that the user_id half of the filter is
    real, not just present in the code."""
    fake = FakeSupabaseClient()
    fake.seed_agent(user_id="user-A", client_id="shared-id", name="User A's Agent", updated_at_ms=1000)
    _patch_client(monkeypatch, fake)

    token_for_user_b = _make_token(user_id="user-B")
    response = client.post(
        "/api/v1/agents/sync/push",
        json={"agents": [{"client_id": "shared-id", "name": "User B's Overwrite Attempt", "created_at_ms": 2000, "updated_at_ms": 2000}]},
        headers={"Authorization": f"Bearer {token_for_user_b}"},
    )

    assert response.status_code == 200
    rows = fake.table("agents").rows
    user_a_row = next(r for r in rows if r["user_id"] == "user-A")
    assert user_a_row["name"] == "User A's Agent"
    user_b_row = next(r for r in rows if r["user_id"] == "user-B")
    assert user_b_row["name"] == "User B's Overwrite Attempt"
    assert len(rows) == 2
