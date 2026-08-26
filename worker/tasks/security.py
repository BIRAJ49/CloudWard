"""Idempotent delivery of validated security jobs to the internal control-plane API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from celery import Task

from worker.celery_app import celery_app

INTERNAL_API = os.getenv(
    "CLOUDWARD_INTERNAL_API_URL", "http://api:8000/api/v1/internal"
).rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_INTERNAL_TOKEN", "local-worker-token-change-me")


def _process_url() -> str:
    url = f"{INTERNAL_API}/security/events/process"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"api", "127.0.0.1"}:
        raise RuntimeError("security worker internal API URL is outside the allowed local boundary")
    return url


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        _process_url(),
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
    name="cloudward.tasks.security.process",
    acks_late=True,
    max_retries=5,
    soft_time_limit=35,
    time_limit=40,
    typing=True,
)
def process_security_event(self: Task, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _post(payload)
    except (HTTPError, URLError, TimeoutError) as exc:
        countdown = min(2 ** (self.request.retries + 1), 30)
        raise self.retry(exc=exc, countdown=countdown)
