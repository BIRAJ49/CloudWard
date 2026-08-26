from types import SimpleNamespace
from unittest.mock import Mock


async def test_healthcheck_publisher_matches_worker_task_signature(
    api_client,
    viewer_headers,  # type: ignore[no-untyped-def]
) -> None:
    publisher = Mock()
    publisher.send_task.return_value = SimpleNamespace(id="task-123")
    api_client._transport.app.state.task_publisher = publisher
    response = await api_client.post(
        "/api/v1/tasks/healthcheck",
        headers={**viewer_headers, "X-Request-ID": "publisher-contract"},
    )
    assert response.status_code == 202, response.text
    assert response.json() == {
        "task_id": "task-123",
        "task_name": "cloudward.tasks.healthcheck",
        "queue": "verification",
    }
    publisher.send_task.assert_called_once_with(
        "cloudward.tasks.healthcheck",
        kwargs={"value": "publisher-contract"},
        queue="verification",
    )
