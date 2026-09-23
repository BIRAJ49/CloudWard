"""A deliberately small workload for deterministic Kubernetes remediation."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.security_scenarios import router as security_router
from app.telemetry import install_http_telemetry, install_tracing

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


class ReleaseMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = SERVICE_NAME
    version: str = SERVICE_VERSION
    environment: str
    source_commit: str | None = None
    image_digest: str | None = None
    release_identifier: str | None = None


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
        return self.bad_release_file.exists() or _env_enabled(
            "DEMO_BAD_RELEASE_ENABLED", False
        )

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


async def _generate_demo_traffic() -> None:
    await asyncio.sleep(1)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8080", timeout=httpx.Timeout(2.0)
    ) as client:
        while True:
            with contextlib.suppress(httpx.HTTPError):
                await client.get("/demo/work", headers={"X-Request-ID": "demo-traffic"})
            await asyncio.sleep(1)


def create_app(
    *,
    state_path: Path | None = None,
    control_enabled: bool | None = None,
    control_auth_required: bool | None = None,
    control_token: str | None = None,
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
    auth_required = (
        _env_enabled("DEMO_CONTROL_AUTH_REQUIRED", False)
        if control_auth_required is None
        else control_auth_required
    )
    expected_control_token = (
        os.getenv("DEMO_CONTROL_TOKEN", "") if control_token is None else control_token
    )
    if auth_required and len(expected_control_token) < 32:
        raise RuntimeError("DEMO_CONTROL_TOKEN must contain at least 32 characters")
    traffic_enabled = _env_enabled("DEMO_TRAFFIC_ENABLED", controls_available)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        traffic_task = (
            asyncio.create_task(_generate_demo_traffic(), name="cloudward-demo-traffic")
            if traffic_enabled
            else None
        )
        try:
            yield
        finally:
            if traffic_task is not None:
                traffic_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await traffic_task

    application = FastAPI(
        title="CloudWard Demo API",
        description=(
            "A controlled health target used to demonstrate deterministic "
            "pod remediation. It contains no random failure behavior."
        ),
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def require_demo_control(
        supplied_token: Annotated[
            str | None, Header(alias="X-CloudWard-Demo-Token")
        ] = None,
    ) -> None:
        _require_controls(
            controls_available,
            auth_required=auth_required,
            supplied_token=supplied_token,
            expected_token=expected_control_token,
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

    @application.get("/metadata", response_model=ReleaseMetadataResponse)
    def release_metadata() -> ReleaseMetadataResponse:
        return ReleaseMetadataResponse(
            environment=environment,
            source_commit=os.getenv("SOURCE_COMMIT") or None,
            image_digest=os.getenv("IMAGE_DIGEST") or None,
            release_identifier=os.getenv("RELEASE_IDENTIFIER") or None,
        )

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

    @application.get(
        "/demo/state",
        response_model=StateResponse,
        dependencies=[Depends(require_demo_control)],
    )
    def get_state() -> StateResponse:
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

    @application.post(
        "/demo/state/bad-release", dependencies=[Depends(require_demo_control)]
    )
    def make_bad_release() -> dict[str, str | bool]:
        failures.enable_bad_release()
        return {"state": "bad_release", "active": True}

    @application.post(
        "/demo/state/bad-release/clear", dependencies=[Depends(require_demo_control)]
    )
    def clear_bad_release() -> dict[str, str | bool]:
        failures.clear_bad_release()
        return {"state": "healthy_release", "active": False}

    @application.post(
        "/demo/state/unhealthy",
        response_model=StateResponse,
        dependencies=[Depends(require_demo_control)],
    )
    def make_unhealthy(
        request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> StateResponse:
        del request_id  # Accepted for cross-service tracing; never persisted here.
        readiness.make_unhealthy()
        return _state_response(readiness)

    @application.post(
        "/demo/state/healthy",
        response_model=StateResponse,
        dependencies=[Depends(require_demo_control)],
    )
    def make_healthy(
        request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> StateResponse:
        del request_id
        readiness.make_healthy()
        return _state_response(readiness)

    application.include_router(
        security_router,
        dependencies=[Depends(require_demo_control)],
    )
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


def _require_controls(
    enabled: bool,
    *,
    auth_required: bool = False,
    supplied_token: str | None = None,
    expected_token: str = "",
) -> None:
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo state controls are disabled",
        )
    if auth_required and (
        supplied_token is None
        or not hmac.compare_digest(supplied_token, expected_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Demo control authentication failed",
        )


def _state_response(readiness: ReadinessState) -> StateResponse:
    return StateResponse(
        state="healthy" if readiness.is_ready else "unhealthy",
        ready=readiness.is_ready,
    )


app = create_app()
