"""Liveness and dependency-aware readiness endpoints."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])


async def _database_check() -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with asyncio.timeout(3), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "up", "latency_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:
        return {"status": "down", "error": type(exc).__name__}


async def _redis_check(redis_client: Redis) -> dict[str, Any]:
    started = time.monotonic()
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=3)
        return {"status": "up", "latency_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:
        return {"status": "down", "error": type(exc).__name__}


async def _opa_check() -> dict[str, Any]:
    settings = get_settings()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{str(settings.opa_url).rstrip('/')}/health?plugins")
            response.raise_for_status()
        return {"status": "up", "latency_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:
        return {"status": "down", "error": type(exc).__name__}


@router.get("/health/live")
async def live() -> dict[str, str]:
    settings = get_settings()
    return {"status": "alive", "service": settings.app_name, "environment": settings.app_env}


async def readiness(request: Request) -> JSONResponse:
    database, redis, opa = await asyncio.gather(
        _database_check(), _redis_check(request.app.state.redis), _opa_check()
    )
    dependencies = {"postgresql": database, "redis": redis, "opa": opa}
    ready = all(item["status"] == "up" for item in dependencies.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "dependencies": dependencies},
    )


router.add_api_route("/health/ready", readiness, methods=["GET"])
