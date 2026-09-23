"""CloudWard FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.health import router as health_router
from app.api.router import api_router
from app.clusters.bootstrap import seed_configured_inventory, seed_development_inventory
from app.config import Settings, get_settings
from app.db.session import SessionFactory, close_database
from app.errors import install_error_handlers
from app.logging import configure_logging
from app.metrics import APIMetricsMiddleware, metrics_response
from app.middleware import RequestContextMiddleware
from app.runbooks import RunbookLoader
from app.security.csrf import CSRFProtectionMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.tasks import create_task_publisher


def _resolve_runbooks_path(settings: Settings) -> Path:
    if settings.runbooks_path.is_dir():
        return settings.runbooks_path
    repository_path = Path(__file__).resolve().parents[2] / "runbooks"
    return repository_path if repository_path.is_dir() else settings.runbooks_path


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.redis = Redis.from_url(
            resolved_settings.redis_url, encoding="utf-8", decode_responses=True
        )
        app.state.runbooks = RunbookLoader(_resolve_runbooks_path(resolved_settings))
        app.state.runbooks.load()
        async with SessionFactory() as session:
            await seed_development_inventory(session, resolved_settings)
            await seed_configured_inventory(session, resolved_settings)
        app.state.task_publisher = create_task_publisher(resolved_settings)
        yield
        await app.state.redis.aclose()
        await close_database()

    app = FastAPI(
        title="CloudWard API",
        description="Controlled reliability, runtime-security, AI diagnosis, and FinOps control plane",
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    app.add_middleware(CSRFProtectionMiddleware, settings=resolved_settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-Request-ID",
            "X-Correlation-ID",
            "X-CloudWard-Dev-User",
            "X-CloudWard-Dev-Role",
            "Last-Event-ID",
        ],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(APIMetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    app.add_api_route("/metrics", metrics_response, methods=["GET"], include_in_schema=False)
    return app


app = create_app()
