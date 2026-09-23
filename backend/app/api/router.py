from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.ai import routes as ai_routes
from app.api import (
    actions,
    approvals,
    audit,
    events,
    finops,
    gitops,
    incident_lab,
    incidents,
    internal_reliability,
    inventory,
    notifications,
    observability,
    roles,
    runbooks,
    security_events,
    task_routes,
    webhooks,
)
from app.api.health import live, readiness
from app.auth.routes import router as auth_router
from app.cluster_agent.routes import router as cluster_agent_router
from app.github import routes as github_routes
from app.incident_memory import routes as incident_memory_routes

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(cluster_agent_router)
api_router.include_router(incidents.router)
api_router.include_router(actions.router)
api_router.include_router(inventory.router)
api_router.include_router(runbooks.router)
api_router.include_router(task_routes.router)
api_router.include_router(roles.router)
api_router.include_router(security_events.router)
api_router.include_router(webhooks.router)
api_router.include_router(incident_lab.router)
api_router.include_router(events.router)
api_router.include_router(internal_reliability.router)
api_router.include_router(observability.router)
api_router.include_router(finops.router)
api_router.include_router(approvals.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)
api_router.include_router(gitops.router)
api_router.include_router(ai_routes.router)
api_router.include_router(ai_routes.internal_router)
api_router.include_router(incident_memory_routes.router)
api_router.include_router(github_routes.router)


@api_router.get("/health", tags=["health"], summary="Dependency-aware readiness health status")
async def versioned_health(request: Request) -> JSONResponse:
    return await readiness(request)


@api_router.get("/health/live", tags=["health"], summary="Liveness probe")
async def versioned_health_live() -> dict[str, str]:
    return await live()


@api_router.get("/health/ready", tags=["health"], summary="Dependency-aware readiness probe")
async def versioned_health_ready(request: Request) -> JSONResponse:
    return await readiness(request)
