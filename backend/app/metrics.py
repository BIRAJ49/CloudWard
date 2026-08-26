"""Low-cardinality operational metrics for the CloudWard control plane."""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

INCIDENTS_TOTAL = Counter(
    "cloudward_incidents_total",
    "CloudWard incidents created",
    ("incident_type", "environment", "severity"),
)
ACTIVE_INCIDENTS = Gauge(
    "cloudward_active_incidents",
    "CloudWard incidents currently non-terminal",
    ("environment",),
)
REMEDIATION_ACTIONS_TOTAL = Counter(
    "cloudward_remediation_actions_total", "Typed remediation actions", ("action", "result")
)
REMEDIATION_FAILURES_TOTAL = Counter(
    "cloudward_remediation_failures_total", "Failed typed remediation actions", ("action",)
)
VERIFICATION_FAILURES_TOTAL = Counter(
    "cloudward_verification_failures_total", "Failed multi-signal verifications", ("strategy",)
)
WEBHOOK_EVENTS_TOTAL = Counter(
    "cloudward_webhook_events_total", "Authenticated webhook events", ("source", "result")
)
SECURITY_EVENTS_TOTAL = Counter(
    "cloudward_security_events_total",
    "Normalized runtime-security events",
    ("category", "severity", "result"),
)
POLICY_DENIALS_TOTAL = Counter(
    "cloudward_policy_denials_total", "OPA policy denials", ("action", "environment")
)
CELERY_TASK_FAILURES_TOTAL = Counter(
    "cloudward_celery_task_failures_total", "Celery job failures", ("task_type",)
)
API_REQUESTS = Counter(
    "cloudward_api_http_requests_total", "CloudWard API requests", ("method", "route", "status")
)
API_DURATION = Histogram(
    "cloudward_api_http_request_duration_seconds",
    "CloudWard API request duration",
    ("method", "route"),
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class APIMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "UNKNOWN")
        started = time.monotonic()
        status = 500

        async def observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            API_REQUESTS.labels(method, template, str(status)).inc()
            API_DURATION.labels(method, template).observe(time.monotonic() - started)
