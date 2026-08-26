import uuid

import pytest

from app.api import health


@pytest.mark.asyncio
async def test_liveness_and_request_identity(api_client) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.get("/health/live", headers={"X-Request-ID": "known-request"})
    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert response.headers["x-request-id"] == "known-request"
    assert response.headers["x-correlation-id"] == "known-request"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(api_client) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.get("/health/live", headers={"X-Request-ID": "bad id\n"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id\n"
    uuid.UUID(response.headers["x-request-id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health/ready", "/api/v1/health"])
async def test_readiness_reports_all_dependencies_up(
    api_client,
    monkeypatch,
    path: str,  # type: ignore[no-untyped-def]
) -> None:
    async def up() -> dict[str, str]:
        return {"status": "up"}

    async def redis_up(redis_client) -> dict[str, str]:  # type: ignore[no-untyped-def]
        assert redis_client is not None
        return {"status": "up"}

    monkeypatch.setattr(health, "_database_check", up)
    monkeypatch.setattr(health, "_redis_check", redis_up)
    monkeypatch.setattr(health, "_opa_check", up)
    response = await api_client.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {
            "postgresql": {"status": "up"},
            "redis": {"status": "up"},
            "opa": {"status": "up"},
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health/ready", "/api/v1/health"])
async def test_readiness_fails_closed_with_machine_readable_dependency_status(
    api_client,
    monkeypatch,
    path: str,  # type: ignore[no-untyped-def]
) -> None:
    async def database_down() -> dict[str, str]:
        return {"status": "down", "error": "ConnectionError"}

    async def up() -> dict[str, str]:
        return {"status": "up"}

    async def redis_up(redis_client) -> dict[str, str]:  # type: ignore[no-untyped-def]
        del redis_client
        return {"status": "up"}

    monkeypatch.setattr(health, "_database_check", database_down)
    monkeypatch.setattr(health, "_redis_check", redis_up)
    monkeypatch.setattr(health, "_opa_check", up)
    response = await api_client.get(path)
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["postgresql"] == {
        "status": "down",
        "error": "ConnectionError",
    }
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "postgresql+asyncpg" not in serialized


@pytest.mark.asyncio
async def test_incident_api_create_list_detail_and_events(
    api_client,
    operator_headers,
    viewer_headers,  # type: ignore[no-untyped-def]
) -> None:
    created = await api_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={
            "incident_type": "reliability",
            "title": "Test incident",
            "environment": "staging",
        },
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["id"]
    assert created.json()["state"] == "DETECTED"

    listed = await api_client.get("/api/v1/incidents", headers=viewer_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [incident_id]

    detail = await api_client.get(f"/api/v1/incidents/{incident_id}", headers=viewer_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["events"][0]["event_type"] == "INCIDENT_CREATED"
    assert detail.json()["audit_events"][0]["event_type"] == "INCIDENT_CREATED"

    timeline = await api_client.get(
        f"/api/v1/incidents/{incident_id}/events", headers=viewer_headers
    )
    assert timeline.status_code == 200
    assert len(timeline.json()) == 1


@pytest.mark.asyncio
async def test_viewer_cannot_create_incident(api_client, viewer_headers) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.post(
        "/api/v1/incidents",
        headers=viewer_headers,
        json={"incident_type": "reliability", "title": "no", "environment": "staging"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_unauthenticated_incident_read_is_rejected(api_client) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.get("/api/v1/incidents")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_invalid_transition_returns_structured_error(
    api_client,
    operator_headers,
    admin_headers,  # type: ignore[no-untyped-def]
) -> None:
    created = await api_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={"incident_type": "reliability", "title": "state", "environment": "staging"},
    )
    response = await api_client.post(
        f"/api/v1/incidents/{created.json()['id']}/transitions",
        headers={**admin_headers, "X-Request-ID": "transition-test"},
        json={"state": "RESOLVED"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "INVALID_INCIDENT_TRANSITION",
            "message": "Cannot transition from DETECTED to RESOLVED",
            "request_id": "transition-test",
            "details": {"from_state": "DETECTED", "to_state": "RESOLVED"},
        }
    }


@pytest.mark.asyncio
async def test_validation_error_uses_error_envelope(api_client, operator_headers) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={"incident_type": "INVALID TYPE", "title": "", "environment": "space"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"]
