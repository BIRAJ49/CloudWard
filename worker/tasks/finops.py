"""Bounded FinOps scenario orchestration through the internal control-plane API."""

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
ALLOWED_SCENARIOS = {
    "finops.overprovisioned-workload",
    "finops.wasted-node-capacity",
}


def _url(scenario_id: str) -> str:
    if scenario_id not in ALLOWED_SCENARIOS:
        raise RuntimeError("FinOps task scenario is outside the fixed catalog")
    return internal_url(INTERNAL_API, f"/finops/scenarios/{scenario_id}/run")


def _post(scenario_id: str, execution_id: str) -> dict[str, Any]:
    return post_json(
        _url(scenario_id), WORKER_TOKEN, {"execution_id": execution_id}, timeout=40
    )


def _mark_failed(execution_id: str, error_code: str) -> dict[str, Any]:
    url = internal_url(
        INTERNAL_API, f"/finops/executions/{uuid.UUID(execution_id)}/fail"
    )
    return post_json(url, WORKER_TOKEN, {"error_code": error_code}, timeout=25)


@celery_app.task(
    bind=True,
    name="cloudward.tasks.finops.scenario",
    acks_late=True,
    max_retries=5,
    soft_time_limit=50,
    time_limit=55,
    typing=True,
)
def run_finops_scenario(
    self: Task,
    scenario_id: str,
    execution_id: str,
) -> dict[str, Any]:
    try:
        return _post(scenario_id, execution_id)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {408, 409, 429}:
            return _mark_failed(execution_id, f"FINOPS_HTTP_{exc.code}")
        if self.request.retries >= self.max_retries:
            return _mark_failed(execution_id, "FINOPS_RETRIES_EXHAUSTED")
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
    except (URLError, TimeoutError) as exc:
        if self.request.retries >= self.max_retries:
            return _mark_failed(execution_id, "FINOPS_PROVIDER_UNAVAILABLE")
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
