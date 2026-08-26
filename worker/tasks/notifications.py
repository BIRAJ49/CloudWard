"""Celery retry boundary for external notification delivery."""

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


def _url(notification_id: str) -> str:
    try:
        import uuid

        normalized = str(uuid.UUID(notification_id))
    except ValueError as exc:
        raise RuntimeError("notification task received an invalid identifier") from exc
    url = f"{INTERNAL_API}/notifications/{normalized}/deliver"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"api", "127.0.0.1"}:
        raise RuntimeError("notification worker internal API URL is outside the allowed boundary")
    return url


def _post(notification_id: str) -> dict[str, Any]:
    request = Request(
        _url(notification_id),
        data=b"{}",
        headers={
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=25) as response:  # noqa: S310 - fixed internal URL
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError("internal API returned a non-object response")
    return result


@celery_app.task(
    bind=True,
    name="cloudward.tasks.notifications.deliver",
    acks_late=True,
    max_retries=5,
    soft_time_limit=30,
    time_limit=35,
    typing=True,
)
def deliver_notification(self: Task, notification_id: str) -> dict[str, Any]:
    try:
        return _post(notification_id)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {404, 408, 409, 429}:
            raise RuntimeError(f"non-retryable internal API response {exc.code}") from exc
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 300))
    except (URLError, TimeoutError) as exc:
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 300))
