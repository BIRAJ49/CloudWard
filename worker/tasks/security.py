"""Idempotent delivery of validated security jobs to the internal control-plane API."""

from __future__ import annotations

import os
from typing import Any
from urllib.error import HTTPError, URLError

from celery import Task

from worker.celery_app import celery_app
from worker.http import internal_url, post_json

INTERNAL_API = os.getenv(
    "CLOUDWARD_INTERNAL_API_URL", "http://api:8000/api/v1/internal"
).rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_INTERNAL_TOKEN", "local-worker-token-change-me")


def _process_url() -> str:
    return internal_url(INTERNAL_API, "/security/events/process")


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return post_json(_process_url(), WORKER_TOKEN, payload, timeout=25)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {408, 409, 429}:
            raise RuntimeError(
                f"non-retryable internal API response {exc.code}"
            ) from exc
        raise


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
