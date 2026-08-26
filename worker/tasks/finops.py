"""Bounded FinOps scenario orchestration through the internal control-plane API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from celery import Task

from worker.celery_app import celery_app

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
    url = f"{INTERNAL_API}/finops/scenarios/{quote(scenario_id, safe='.-')}/run"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"api", "127.0.0.1"}:
        raise RuntimeError("FinOps worker internal API URL is outside the allowed local boundary")
    return url


def _post(scenario_id: str, execution_id: str) -> dict[str, Any]:
    request = Request(
        _url(scenario_id),
        data=json.dumps({"execution_id": execution_id}, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=40) as response:  # noqa: S310 - fixed internal URL
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError("internal API returned a non-object response")
    return result


def _mark_failed(execution_id: str, error_code: str) -> dict[str, Any]:
    url = f"{INTERNAL_API}/finops/executions/{execution_id}/fail"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"api", "127.0.0.1"}:
        raise RuntimeError("FinOps worker internal API URL is outside the allowed local boundary")
    request = Request(
        url,
        data=json.dumps({"error_code": error_code}, separators=(",", ":")).encode(),
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
