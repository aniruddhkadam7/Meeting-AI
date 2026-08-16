from fastapi import APIRouter

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

api_router = APIRouter()
api_router.include_router(health.router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(interviews.router)
v1_router.include_router(ask.router)
v1_router.include_router(setup.router)
v1_router.include_router(sales.router)
v1_router.include_router(consulting.router)
v1_router.include_router(notes.router)
v1_router.include_router(agents.router)
v1_router.include_router(agent_sync.router)
v1_router.include_router(analytics.router)
