"""Forces the deterministic mock LLM provider for the whole test suite.

`app/core/config.py` calls `load_dotenv(...)`, which never overrides variables
already present in the environment, and `Settings` reads `os.getenv` at class
definition (import) time. Setting these here — in conftest, which pytest
imports before any test module, and therefore before `app.main` is first
imported — is what makes the override actually take effect.

Without this, a developer with a real `OPENAI_API_KEY` in `apps/backend/.env`
runs the entire suite against the live API: slow, billable, and flaky offline.
Nothing above this line may import from `app`.
"""

import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

# Fixed test-only JWT secret so auth-gated route tests (test_auth.py) can
# mint valid tokens without a real Supabase project. Settings reads env vars
# at class-definition (import) time, so this must be set before app.main
# (and therefore app.core.config) is first imported — same reasoning as the
# LLM_PROVIDER override above.
os.environ["SUPABASE_JWT_SECRET"] = "test-jwt-secret-for-unit-tests-only"
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

import pytest


@pytest.fixture(autouse=True)
def _reset_llm_rate_limiter():
    """TestClient requests all share one `request.client.host`, so without
    this every test file would draw down the same rate-limit bucket
    (app/core/rate_limit.py) and the suite would start failing with 429s
    once enough LLM-route tests run in one process — not a real limit being
    hit, just cross-test bucket sharing. Reset before every test so each one
    starts with a fresh budget; test_rate_limit.py exercises the real
    enforcement behavior directly against a fresh limiter instance."""
    from app.core.rate_limit import llm_rate_limiter

    llm_rate_limiter._hits.clear()
    yield
