from fastapi import APIRouter, Depends

from app.api.routes import (
    agent_sync,
    agents,
    analytics,
    ask,
    consulting,
    health,
    interviews,
    notes,
    sales,
    setup,
)
from app.core.rate_limit import enforce_llm_rate_limit

api_router = APIRouter()
api_router.include_router(health.router)

v1_router = APIRouter(prefix="/api/v1")

# These routers accept no authentication by design (stateless LLM
# pass-throughs — see each route's docstring), so a per-IP rate limit is the
# only thing standing between "anonymous user" and "anonymous user driving
# unbounded OpenAI/Anthropic spend". See app/core/rate_limit.py.
_llm_rate_limit = [Depends(enforce_llm_rate_limit)]
v1_router.include_router(interviews.router, dependencies=_llm_rate_limit)
v1_router.include_router(ask.router, dependencies=_llm_rate_limit)
v1_router.include_router(setup.router, dependencies=_llm_rate_limit)
v1_router.include_router(sales.router, dependencies=_llm_rate_limit)
v1_router.include_router(consulting.router, dependencies=_llm_rate_limit)
v1_router.include_router(notes.router, dependencies=_llm_rate_limit)
v1_router.include_router(agents.router, dependencies=_llm_rate_limit)
v1_router.include_router(agent_sync.router)
v1_router.include_router(analytics.router)
