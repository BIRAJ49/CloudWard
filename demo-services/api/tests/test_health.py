from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def client(state_file: Path, *, controls: bool = True) -> TestClient:
    return TestClient(create_app(state_path=state_file, control_enabled=controls))


def test_default_health_endpoints(tmp_path: Path) -> None:
    api = client(tmp_path / "unhealthy")

    root = api.get("/")
    live = api.get("/health/live")
    ready = api.get("/health/ready")

    assert root.status_code == 200
    assert root.json()["ready"] is True
    assert live.status_code == 200
    assert live.json()["status"] == "alive"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    metadata = api.get("/metadata")
    assert metadata.status_code == 200
    assert metadata.json()["service"] == "cloudward-demo-api"
    assert metadata.json()["environment"] in {"local", "staging", "production"}


def test_controlled_failure_only_changes_readiness(tmp_path: Path) -> None:
    state_file = tmp_path / "nested" / "unhealthy"
    api = client(state_file)

    trigger = api.post(
        "/demo/state/unhealthy",
        headers={"X-Request-ID": "incident-correlation-1"},
    )

    assert trigger.status_code == 200
    assert trigger.json() == {
        "service": "cloudward-demo-api",
        "state": "unhealthy",
        "ready": False,
        "mechanism": "sentinel_file",
    }
    assert state_file.exists()
    assert api.get("/health/ready").status_code == 503
    assert api.get("/health/ready").json()["reason"] == "controlled_demo_failure"
    assert api.get("/health/live").status_code == 200

    recovery = api.post("/demo/state/healthy")

    assert recovery.status_code == 200
    assert recovery.json()["ready"] is True
    assert not state_file.exists()
    assert api.get("/health/ready").status_code == 200


def test_control_endpoints_can_be_disabled(tmp_path: Path) -> None:
    api = client(tmp_path / "unhealthy", controls=False)

    assert api.get("/demo/state").status_code == 404
    assert api.post("/demo/state/unhealthy").status_code == 404
    assert api.post("/demo/state/healthy").status_code == 404
    assert api.get("/health/ready").status_code == 200


def test_control_and_security_endpoints_require_configured_token(
    tmp_path: Path,
) -> None:
    token = "a" * 32
    api = TestClient(
        create_app(
            state_path=tmp_path / "unhealthy",
            control_enabled=True,
            control_auth_required=True,
            control_token=token,
        )
    )

    assert api.post("/demo/state/unhealthy").status_code == 401
    assert api.get("/demo/security/egress-probe").status_code == 401
    assert (
        api.post(
            "/demo/state/unhealthy",
            headers={"X-CloudWard-Demo-Token": token},
        ).status_code
        == 200
    )
