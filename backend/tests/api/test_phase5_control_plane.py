"""Phase 5 Control Plane Foundation verification tests."""

from __future__ import annotations

import pytest

from app.api import health


@pytest.mark.asyncio
async def test_phase5_versioned_health_endpoints(api_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify versioned health, liveness, and readiness endpoints."""
    live_resp = await api_client.get("/api/v1/health/live")
    assert live_resp.status_code == 200
    assert live_resp.json()["status"] == "alive"

    async def up() -> dict[str, str]:
        return {"status": "up"}

    async def redis_up(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
        return {"status": "up"}

    monkeypatch.setattr(health, "_database_check", up)
    monkeypatch.setattr(health, "_redis_check", redis_up)
    monkeypatch.setattr(health, "_opa_check", up)

    ready_resp = await api_client.get("/api/v1/health/ready")
    assert ready_resp.status_code == 200
    data = ready_resp.json()
    assert data["status"] == "ready"
    assert "postgresql" in data["dependencies"]
    assert "redis" in data["dependencies"]
    assert "opa" in data["dependencies"]


@pytest.mark.asyncio
async def test_incident_patch_and_resolve(
    api_client,
    operator_headers,
    viewer_headers,  # type: ignore[no-untyped-def]
) -> None:
    """Verify incident update and resolution routes."""
    create_resp = await api_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={
            "incident_type": "reliability",
            "title": "Initial Title",
            "summary": "Initial summary",
            "environment": "staging",
        },
    )
    assert create_resp.status_code == 201
    incident_id = create_resp.json()["id"]

    # Viewers cannot patch
    forbidden_patch = await api_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=viewer_headers,
        json={"title": "Unauthorized Title"},
    )
    assert forbidden_patch.status_code == 403

    # Operators can patch
    patch_resp = await api_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=operator_headers,
        json={
            "title": "Updated Title",
            "summary": "Updated summary",
            "severity": "CRITICAL",
        },
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["title"] == "Updated Title"
    assert updated["summary"] == "Updated summary"
    assert updated["severity"] == "CRITICAL"

    # Operators can resolve
    resolve_resp = await api_client.post(
        f"/api/v1/incidents/{incident_id}/resolve",
        headers=operator_headers,
        json={"reason": "Self-healed by operator", "source": "human_action"},
    )
    assert resolve_resp.status_code == 200
    resolved = resolve_resp.json()
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolved_at"] is not None
    assert resolved["resolution_source"] == "HUMAN_ACTION"


@pytest.mark.asyncio
async def test_incident_evidence_crud(
    api_client,
    operator_headers,
    viewer_headers,  # type: ignore[no-untyped-def]
) -> None:
    """Verify normalized evidence addition and retrieval."""
    create_resp = await api_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={
            "incident_type": "reliability",
            "title": "Evidence Test Incident",
            "environment": "staging",
        },
    )
    assert create_resp.status_code == 201
    incident_id = create_resp.json()["id"]

    # Viewers cannot add evidence
    forbid_evidence = await api_client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=viewer_headers,
        json={
            "evidence_type": "METRIC",
            "summary": "High CPU utilization: 98%",
            "source": "prometheus",
            "payload": {"cpu_percent": 98.2},
        },
    )
    assert forbid_evidence.status_code == 403

    # Operators can add evidence
    add_resp = await api_client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=operator_headers,
        json={
            "evidence_type": "METRIC",
            "summary": "High CPU utilization: 98%",
            "source": "prometheus",
            "payload": {"cpu_percent": 98.2},
        },
    )
    assert add_resp.status_code == 201
    evidence_data = add_resp.json()
    assert evidence_data["evidence_type"] == "METRIC"
    assert evidence_data["summary"] == "High CPU utilization: 98%"

    # Add second evidence item
    add_resp2 = await api_client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=operator_headers,
        json={
            "evidence_type": "KUBERNETES_STATE",
            "summary": "CrashLoopBackOff detected on pod payments-abc-123",
            "source": "kubernetes",
            "payload": {"pod": "payments-abc-123", "restart_count": 5},
        },
    )
    assert add_resp2.status_code == 201

    # Viewers can list evidence
    list_resp = await api_client.get(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=viewer_headers,
    )
    assert list_resp.status_code == 200
    evidence_list = list_resp.json()
    assert len(evidence_list) == 2
    types = [e["evidence_type"] for e in evidence_list]
    assert "METRIC" in types
    assert "KUBERNETES_STATE" in types


@pytest.mark.asyncio
async def test_action_catalog_and_evaluation(
    api_client,
    operator_headers,
    viewer_headers,  # type: ignore[no-untyped-def]
) -> None:
    """Verify action catalog listing, retrieval, and deterministic evaluation."""
    # List actions
    list_resp = await api_client.get("/api/v1/actions", headers=viewer_headers)
    assert list_resp.status_code == 200
    actions = list_resp.json()
    action_types = [a["action_type"] for a in actions]
    assert "DELETE_UNHEALTHY_POD" in action_types
    assert "RESTART_POD" in action_types
    assert "SCALE_WORKLOAD" in action_types
    assert "ROLLBACK_DEPLOYMENT" in action_types
    assert "QUARANTINE_WORKLOAD" in action_types

    # Specific action metadata
    meta_resp = await api_client.get(
        "/api/v1/actions/RESTART_POD",
        headers=viewer_headers,
    )
    assert meta_resp.status_code == 200
    meta = meta_resp.json()
    assert meta["action_type"] == "RESTART_POD"
    assert meta["reversible"] is True

    # Evaluate action
    eval_resp = await api_client.post(
        "/api/v1/actions/evaluate",
        headers=operator_headers,
        json={
            "action_type": "RESTART_POD",
            "environment": "staging",
            "parameters": {"target_count": 1},
        },
    )
    assert eval_resp.status_code == 200
    evaluation = eval_resp.json()
    assert evaluation["action_type"] == "RESTART_POD"
    assert evaluation["environment"] == "staging"
    assert "risk_score" in evaluation
    assert "classification" in evaluation
    assert "factors" in evaluation
