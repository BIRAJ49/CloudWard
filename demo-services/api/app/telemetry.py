"""Low-cardinality metrics, JSON logs, and OpenTelemetry for the demo workload."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS = Counter(
    "cloudward_demo_http_requests_total",
    "Completed CloudWard demo HTTP requests",
    ("service", "method", "route", "status_code"),
)
HTTP_DURATION = Histogram(
    "cloudward_demo_http_request_duration_seconds",
    "CloudWard demo HTTP request duration",
    ("service", "method", "route", "status_code"),
    # Keep 6–12 second demo degradations distinguishable from +Inf.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 8, 12, 20, 30),
)
IN_FLIGHT = Gauge(
    "cloudward_demo_http_requests_in_flight",
    "CloudWard demo requests currently executing",
    ("service", "method", "route"),
)
READINESS = Gauge(
    "cloudward_demo_readiness",
    "Whether the CloudWard demo application is ready",
    ("service",),
)
FAILURE_ACTIVE = Gauge(
    "cloudward_demo_failure_injection_active",
    "Whether a fixed controlled demo failure is active",
    ("service", "failure_type"),
)

EXCLUDED_TRACE_PATHS = "/metrics,/health/live,/health/ready"
KNOWN_ROUTES = (
    "/",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/demo/state",
    "/demo/state/unhealthy",
    "/demo/state/healthy",
    "/demo/state/bad-release",
    "/demo/state/bad-release/clear",
    "/demo/work",
    "/demo/slow",
)
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger("cloudward.demo")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)


def _route(path: str) -> str:
    return path if path in KNOWN_ROUTES else "unmatched"


def _trace_ids() -> tuple[str | None, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def _log_event(
    *,
    level: int,
    message: str,
    event: str,
    request_id: str,
    environment: str,
    fields: dict[str, object],
) -> None:
    trace_id, span_id = _trace_ids()
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "service": os.getenv("OTEL_SERVICE_NAME", "cloudward-demo-api"),
        "environment": environment,
        "request_id": request_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "message": message,
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":"), default=str))


def install_http_telemetry(
    app: FastAPI,
    *,
    service_name: str,
    environment: str,
    readiness: Callable[[], bool],
    failures: Callable[[], dict[str, bool]],
) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next: Callable[..., object]) -> Response:
        route = _route(request.url.path)
        method = request.method.upper()
        supplied = request.headers.get("x-request-id", "")
        request_id = (
            supplied if SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
        )
        token = IN_FLIGHT.labels(service_name, method, route)
        token.inc()
        started = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)  # type: ignore[arg-type]
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.monotonic() - started
            token.dec()
            status = str(status_code)
            HTTP_REQUESTS.labels(service_name, method, route, status).inc()
            HTTP_DURATION.labels(service_name, method, route, status).observe(duration)
            READINESS.labels(service_name).set(1 if readiness() else 0)
            for failure_type, active in failures().items():
                FAILURE_ACTIVE.labels(service_name, failure_type).set(
                    1 if active else 0
                )
            if route not in {"/metrics", "/health/live", "/health/ready"}:
                _log_event(
                    level=logging.INFO,
                    message="request completed",
                    event="http.request.completed",
                    request_id=request_id,
                    environment=environment,
                    fields={
                        "method": method,
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 2),
                    },
                )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def install_tracing(
    app: FastAPI, *, service_name: str, service_version: str, environment: str
) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "service.version": service_version,
                    "deployment.environment": environment,
                    "cloudward.demo": True,
                }
            )
        )
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=EXCLUDED_TRACE_PATHS,
        tracer_provider=trace.get_tracer_provider(),
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=trace.get_tracer_provider())
