from worker.celery_app import QUEUE_NAMES, celery_app
from worker.tasks.health import healthcheck


def test_healthcheck_task_invocation() -> None:
    result = healthcheck.run("part-1", request_id="request-123")

    assert result == {
        "status": "ok",
        "echo": "part-1",
        "worker": "cloudward-worker",
        "request_id": "request-123",
    }
    assert healthcheck.name == "cloudward.tasks.healthcheck"


def test_healthcheck_preserves_legacy_value_correlation() -> None:
    result = healthcheck.run("api-request-id")

    assert result["echo"] == "api-request-id"
    assert result["request_id"] == "api-request-id"


def test_logical_queues_and_task_route_are_configured() -> None:
    configured_queues = {queue.name for queue in celery_app.conf.task_queues}

    assert configured_queues == set(QUEUE_NAMES)
    assert celery_app.conf.task_default_queue == "incident-ingestion"
    assert celery_app.conf.task_routes["cloudward.tasks.healthcheck"] == {
        "queue": "verification",
        "routing_key": "verification",
    }
