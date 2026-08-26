"""Small broker round-trip task used to prove the worker is operational."""

from __future__ import annotations

from typing import TypedDict

from worker.celery_app import celery_app


class HealthcheckResult(TypedDict):
    status: str
    echo: str
    worker: str
    request_id: str | None


@celery_app.task(name="cloudward.tasks.healthcheck", typing=True)
def healthcheck(
    value: str = "ping", request_id: str | None = None
) -> HealthcheckResult:
    """Return a JSON-serializable result after actual worker execution."""

    correlation_id = request_id or (value if value != "ping" else None)
    return {
        "status": "ok",
        "echo": value,
        "worker": "cloudward-worker",
        "request_id": correlation_id,
    }
