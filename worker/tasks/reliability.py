"""Bounded Celery orchestration for reliability evidence and scenario monitoring."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from celery import Task

from worker.celery_app import celery_app

INTERNAL_API = os.getenv("CLOUDWARD_INTERNAL_API_URL", "http://api:8000/api/v1/internal").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_INTERNAL_TOKEN", "local-worker-token-change-me")


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{INTERNAL_API}{path}",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:  # noqa: S310 - fixed internal URL
            result = json.load(response)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {408, 409, 429}:
            raise RuntimeError(f"non-retryable internal API response {exc.code}") from exc
        raise
    if not isinstance(result, dict):
        raise RuntimeError("internal API returned a non-object response")
    return result


@celery_app.task(
    bind=True,
    name="cloudward.tasks.alerts.process",
    acks_late=True,
    max_retries=5,
    soft_time_limit=40,
    time_limit=45,
    typing=True,
)
def process_alert(
    self: Task,
    incident_id: str,
    alert: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    try:
        return _post(
            "/reliability/process-alert",
            {"incident_id": incident_id, "alert": alert, "correlation_id": correlation_id},
        )
    except (URLError, TimeoutError) as exc:
        countdown = min(2 ** (self.request.retries + 1), 30)
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(
    bind=True,
    name="cloudward.tasks.scenarios.monitor",
    acks_late=True,
    max_retries=80,
    soft_time_limit=35,
    time_limit=40,
    typing=True,
)
def monitor_scenario(self: Task, execution_id: str) -> dict[str, Any]:
    try:
        result = _post(f"/executions/{execution_id}/reconcile", {})
    except (URLError, TimeoutError) as exc:
        countdown = min(2 ** (self.request.retries + 1), 30)
        raise self.retry(exc=exc, countdown=countdown)
    if not bool(result.get("terminal")):
        retry_after = int(result.get("retry_after_seconds", 5))
        raise self.retry(countdown=min(max(retry_after, 2), 30))
    return result
