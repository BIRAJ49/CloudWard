"""A deliberately small workload for deterministic Kubernetes remediation."""

from __future__ import annotations

import os
import time
import asyncio
import contextlib
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel, ConfigDict

from app.telemetry import install_http_telemetry, install_tracing
from app.security_scenarios import router as security_router

SERVICE_NAME = "cloudward-demo-api"
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.2.0")
DEFAULT_STATE_FILE = "/tmp/cloudward-demo/unhealthy"
BAD_RELEASE_STATE_FILE = "/tmp/cloudward-demo/bad-release"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = SERVICE_NAME
    status: str
    ready: bool | None = None
    reason: str | None = None
    version: str = SERVICE_VERSION


class StateResponse(BaseModel):
    service: str = SERVICE_NAME
    state: str
    ready: bool
    mechanism: str = "sentinel_file"


class ReadinessState:
    """Container-local state that resets naturally when Kubernetes replaces a pod."""

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file

    @property
    def is_ready(self) -> bool:
        return not self.state_file.exists()

    def make_unhealthy(self) -> None:
        self.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_file.write_text("controlled-demo-failure\n", encoding="utf-8")

    def make_healthy(self) -> None:
        self.state_file.unlink(missing_ok=True)


class FailureState:
    def __init__(self, state_directory: Path) -> None:
        self.bad_release_file = state_directory / "bad-release"

    @property
    def bad_release(self) -> bool:
        return self.bad_release_file.exists() or _env_enabled("DEMO_BAD_RELEASE_ENABLED", False)

    def enable_bad_release(self) -> None:
        self.bad_release_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.bad_release_file.write_text("controlled-bad-release\n", encoding="utf-8")

    def clear_bad_release(self) -> None:
        self.bad_release_file.unlink(missing_ok=True)

    def metrics(self) -> dict[str, bool]:
        return {
            "readiness": False,
            "bad_release": self.bad_release,
            "cpu_stress": False,
            "memory_stress": False,
        }


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app(
    *,
    state_path: Path | None = None,
    control_enabled: bool | None = None,
) -> FastAPI:
    readiness = ReadinessState(
        state_path or Path(os.getenv("DEMO_UNHEALTHY_STATE_FILE", DEFAULT_STATE_FILE))
    )
    failures = FailureState(readiness.state_file.parent)
    environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "local")
    controls_available = (
        _env_enabled("DEMO_CONTROL_ENABLED", True)
        if control_enabled is None
        else control_enabled
    )
    traffic_enabled = _env_enabled("DEMO_TRAFFIC_ENABLED", controls_available)
    traffic_task: asyncio.Task[None] | None = None

    application = FastAPI(
        title="CloudWard Demo API",
        description=(
            "A controlled health target used to demonstrate deterministic "
            "pod remediation. It contains no random failure behavior."
        ),
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    @application.get("/", response_model=HealthResponse)
    def root() -> HealthResponse:
        return HealthResponse(
            status="healthy" if readiness.is_ready else "unhealthy",
            ready=readiness.is_ready,
        )

    @application.get("/health/live", response_model=HealthResponse)
    def live() -> HealthResponse:
        # Controlled readiness failure must never make the process appear dead.
        return HealthResponse(status="alive")

    @application.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
    )
    def ready() -> HealthResponse | JSONResponse:
        if readiness.is_ready:
            return HealthResponse(status="ready", ready=True)
        payload = HealthResponse(
            status="unhealthy",
            ready=False,
            reason="controlled_demo_failure",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )

    @application.get("/demo/state", response_model=StateResponse)
    def get_state() -> StateResponse:
        _require_controls(controls_available)
        return _state_response(readiness)

    @application.get("/demo/work")
    def work() -> JSONResponse:
        if failures.bad_release:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "status": "failed",
                    "reason": "controlled_bad_release",
                    "version": SERVICE_VERSION,
                },
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "version": SERVICE_VERSION},
        )

    @application.get("/demo/slow")
    def slow() -> dict[str, str | float]:
        delay = min(max(float(os.getenv("DEMO_FIXED_LATENCY_SECONDS", "8")), 1.0), 12.0)
        time.sleep(delay)
        return {"status": "ok", "controlled_delay_seconds": delay}

    @application.post("/demo/state/bad-release")
    def make_bad_release() -> dict[str, str | bool]:
        _require_controls(controls_available)
        failures.enable_bad_release()
        return {"state": "bad_release", "active": True}

    @application.post("/demo/state/bad-release/clear")
    def clear_bad_release() -> dict[str, str | bool]:
        _require_controls(controls_available)
        failures.clear_bad_release()
        return {"state": "healthy_release", "active": False}

    async def generate_demo_traffic() -> None:
        await asyncio.sleep(1)
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8080", timeout=httpx.Timeout(2.0)
        ) as client:
            while True:
                try:
                    await client.get("/demo/work", headers={"X-Request-ID": "demo-traffic"})
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)

    async def start_demo_traffic() -> None:
        nonlocal traffic_task
        if traffic_enabled:
            traffic_task = asyncio.create_task(
                generate_demo_traffic(), name="cloudward-demo-traffic"
            )

    async def stop_demo_traffic() -> None:
        if traffic_task is not None:
            traffic_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await traffic_task

    application.add_event_handler("startup", start_demo_traffic)
    application.add_event_handler("shutdown", stop_demo_traffic)

    @application.post("/demo/state/unhealthy", response_model=StateResponse)
    def make_unhealthy(
        request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> StateResponse:
        del request_id  # Accepted for cross-service tracing; never persisted here.
        _require_controls(controls_available)
        readiness.make_unhealthy()
        return _state_response(readiness)

    @application.post("/demo/state/healthy", response_model=StateResponse)
    def make_healthy(
        request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> StateResponse:
        del request_id
        _require_controls(controls_available)
        readiness.make_healthy()
        return _state_response(readiness)

    application.include_router(security_router)
    install_http_telemetry(
        application,
        service_name=SERVICE_NAME,
        environment=environment,
        readiness=lambda: readiness.is_ready,
        failures=failures.metrics,
    )
    install_tracing(
        application,
        service_name=SERVICE_NAME,
        service_version=SERVICE_VERSION,
        environment=environment,
    )
    return application


def _require_controls(enabled: bool) -> None:
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo state controls are disabled",
        )


def _state_response(readiness: ReadinessState) -> StateResponse:
    return StateResponse(
        state="healthy" if readiness.is_ready else "unhealthy",
        ready=readiness.is_ready,
    )


app = create_app()
