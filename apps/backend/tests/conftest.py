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
