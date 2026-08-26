from __future__ import annotations

import os

import pytest
from worker.tasks.health import healthcheck


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("CELERY_INTEGRATION") != "1",
    reason="set CELERY_INTEGRATION=1 with Redis and a worker running",
)
def test_healthcheck_traverses_redis_and_worker() -> None:
    result = healthcheck.apply_async(
        args=("redis-round-trip",),
        kwargs={"request_id": "integration-request"},
        queue="verification",
    )

    assert result.get(timeout=15) == {
        "status": "ok",
        "echo": "redis-round-trip",
        "worker": "cloudward-worker",
        "request_id": "integration-request",
    }
