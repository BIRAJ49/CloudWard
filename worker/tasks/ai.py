"""Asynchronous supplemental diagnosis that never blocks deterministic remediation."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from celery import Task

from worker.celery_app import celery_app

INTERNAL_API = os.getenv(
    "CLOUDWARD_INTERNAL_API_URL", "http://api:8000/api/v1/internal"
).rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_INTERNAL_TOKEN", "local-worker-token-change-me")


@celery_app.task(
    bind=True,
    name="cloudward.tasks.ai.diagnose",
    acks_late=True,
    max_retries=2,
    soft_time_limit=300,
    time_limit=330,
    typing=True,
)
def diagnose_incident(self: Task, incident_id: str) -> dict[str, object]:
    request = Request(
        f"{INTERNAL_API}/ai/incidents/{incident_id}/diagnose",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=290) as response:  # noqa: S310 - fixed internal URL
            result = json.load(response)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {408, 409, 429}:
            raise RuntimeError(f"non-retryable internal AI response {exc.code}") from exc
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
    except (URLError, TimeoutError) as exc:
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
    if not isinstance(result, dict):
        raise RuntimeError("internal AI endpoint returned a non-object response")
    return result
