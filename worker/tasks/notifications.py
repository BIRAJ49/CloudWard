"""Celery retry boundary for external notification delivery."""

from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.error import HTTPError, URLError

from celery import Task

from worker.celery_app import celery_app
from worker.http import internal_url, post_json

INTERNAL_API = os.getenv(
    "CLOUDWARD_INTERNAL_API_URL", "http://api:8000/api/v1/internal"
).rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_INTERNAL_TOKEN", "local-worker-token-change-me")


def _url(notification_id: str) -> str:
    try:
        normalized = str(uuid.UUID(notification_id))
    except ValueError as exc:
        raise RuntimeError("notification task received an invalid identifier") from exc
    return internal_url(INTERNAL_API, f"/notifications/{normalized}/deliver")


def _post(notification_id: str) -> dict[str, Any]:
    return post_json(_url(notification_id), WORKER_TOKEN, {}, timeout=25)


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
            raise RuntimeError(
                f"non-retryable internal API response {exc.code}"
            ) from exc
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 300))
    except (URLError, TimeoutError) as exc:
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 300))
