from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.cluster_agent.collector import AgentCollector, KubernetesReader
from app.cluster_agent.config import AgentSettings
from app.cluster_agent.models import ClusterAgentState
from app.cluster_agent.runtime import ReportPublisher
from app.cluster_agent.schemas import AgentReport
from app.cluster_agent.service import connection_status, ingest_report
from app.db.models import (
    ActionExecution,
    AuditEvent,
    Cluster,
    Environment,
    EvidenceSnapshot,
    Incident,
    Service,
    StreamEvent,
)
from app.errors import CloudWardError
from app.finops.schemas import CostAllocation
from app.incidents.state_machine import IncidentState

AGENT_TOKEN = "test-agent-credential-" + "a" * 32


@pytest.fixture
async def agent_inventory(session, settings):
    cluster = Cluster(name="agent-test", environment=Environment.STAGING, status="CONFIGURED")
    session.add(cluster)
    await session.flush()
    service = Service(
        cluster_id=cluster.id,
        name="cloudward-demo",
        namespace="cloudward-staging",
        deployment_name="cloudward-demo",
    )
    session.add(service)
    await session.flush()
    incident = Incident(
        cluster_id=cluster.id,
        service_id=service.id,
        correlation_id="agent-test",
        incident_type="reliability",
        title="Unhealthy workload",
        environment=Environment.STAGING,
    )
    session.add(incident)
    await session.commit()
    settings.cluster_agent_enabled = True
    settings.cluster_agent_cluster_id = cluster.id
    settings.cluster_agent_token = SecretStr(AGENT_TOKEN)
    return cluster, service, incident


def report(cluster_id, *, observed_at=None):
    now = observed_at or datetime.now(UTC)
    return {
        "schema_version": 1,
        "report_id": str(uuid.uuid4()),
        "cluster_id": str(cluster_id),
        "observed_at": now.isoformat(),
        "workloads": [
            {
                "target": {
                    "namespace": "cloudward-staging",
                    "service": "cloudward-demo",
                    "deployment": "cloudward-demo",
                },
                "deployment": {
                    "generation": 3,
                    "observed_generation": 3,
                    "desired_replicas": 2,
                    "ready_replicas": 1,
                    "updated_replicas": 2,
                    "pods": [],
                },
                "telemetry": [
                    {
                        "provider": "loki",
                        "query": "{}",
                        "window": {
                            "start": (now - timedelta(minutes=5)).isoformat(),
                            "end": now.isoformat(),
                        },
                        "samples": [
                            {
                                "line": "password=must-not-leak",
                                "authorization": "Bearer do-not-store",
                            }
                        ],
                    }
                ],
            }
        ],
    }


async def test_agent_intake_evidence_inventory_rbac_and_idempotency(
    api_client, agent_inventory, viewer_headers, session
):
    cluster, _, incident = agent_inventory
    payload = report(cluster.id)
    unauthorized = await api_client.post("/api/v1/agent/reports", json=payload)
    assert unauthorized.status_code == 401
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
    accepted = await api_client.post("/api/v1/agent/reports", json=payload, headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["attached_incidents"] == 1
    duplicate = await api_client.post("/api/v1/agent/reports", json=payload, headers=headers)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"]
    assert await session.scalar(select(func.count()).select_from(EvidenceSnapshot)) == 2
    assert await session.scalar(select(func.count()).select_from(ActionExecution)) == 0
    await session.refresh(incident)
    assert incident.state == IncidentState.DETECTED
    assert (await api_client.get(f"/api/v1/agent/clusters/{cluster.id}")).status_code == 401
    detail = await api_client.get(f"/api/v1/agent/clusters/{cluster.id}", headers=viewer_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "CONNECTED"
    assert detail.json()["authority"] == "evidence_only"
    assert "must-not-leak" not in detail.text
    assert "do-not-store" not in detail.text
    evidence = await api_client.get(
        f"/api/v1/observability/incidents/{incident.id}/evidence", headers=viewer_headers
    )
    assert len(evidence.json()) == 2
    assert "must-not-leak" not in evidence.text
    inventory = await api_client.get("/api/v1/clusters", headers=viewer_headers)
    assert inventory.json()[0]["status"] == "CONNECTED"
    assert inventory.json()[0]["agent_observed_at"]
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "CLUSTER_AGENT_STATUS_CHANGED")
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(StreamEvent)
            .where(StreamEvent.event_type == "cluster.observation")
        )
        == 1
    )


@pytest.mark.parametrize(
    "change,status",
    [
        ("cluster", 403),
        ("target", 403),
        ("namespace", 422),
        ("stale", 422),
        ("future", 422),
        ("extra", 422),
    ],
)
async def test_report_cannot_escape_identity_schema_or_freshness(
    api_client, agent_inventory, session, change, status
):
    cluster, _, _ = agent_inventory
    payload = report(cluster.id)
    if change == "cluster":
        payload["cluster_id"] = str(uuid.uuid4())
    elif change == "target":
        payload["workloads"][0]["target"]["deployment"] = "unregistered"
    elif change == "namespace":
        payload["workloads"][0]["target"]["namespace"] = "kube-system"
    elif change in {"stale", "future"}:
        payload = report(
            cluster.id,
            observed_at=datetime.now(UTC) + timedelta(minutes=10 if change == "future" else -10),
        )
    else:
        payload["command"] = "password=must-not-echo"
    response = await api_client.post(
        "/api/v1/agent/reports", json=payload, headers={"Authorization": f"Bearer {AGENT_TOKEN}"}
    )
    assert response.status_code == status, response.text
    assert "must-not-echo" not in response.text
    assert await session.scalar(select(func.count()).select_from(ClusterAgentState)) == 0
    assert await session.scalar(select(func.count()).select_from(EvidenceSnapshot)) == 0


async def test_disabled_agent_never_accepts_reports(api_client):
    response = await api_client.post("/api/v1/agent/reports", json={})
    assert response.status_code == 503


async def test_agent_streamed_body_limit(api_client, agent_inventory):
    async def chunks():
        yield b"x" * 300_000
        yield b"x" * 300_000

    response = await api_client.post(
        "/api/v1/agent/reports",
        content=chunks(),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 413


async def test_report_conflict_reordering_rate_and_stale_status(session, settings, agent_inventory):
    cluster, _, _ = agent_inventory
    now = datetime.now(UTC)
    first = AgentReport.model_validate(report(cluster.id, observed_at=now))
    await ingest_report(session, first, settings, now=now)
    await session.commit()
    changed = first.model_copy(update={"observed_at": now + timedelta(seconds=1)})
    with pytest.raises(CloudWardError, match="different content"):
        await ingest_report(session, changed, settings, now=now)
    old = first.model_copy(
        update={"report_id": uuid.uuid4(), "observed_at": now - timedelta(seconds=1)}
    )
    with pytest.raises(CloudWardError, match="older observation"):
        await ingest_report(session, old, settings, now=now)
    new = AgentReport.model_validate(report(cluster.id, observed_at=now + timedelta(seconds=5)))
    with pytest.raises(CloudWardError, match="ten seconds"):
        await ingest_report(session, new, settings, now=now + timedelta(seconds=5))
    state = await session.get(ClusterAgentState, cluster.id)
    assert connection_status(state, max_age=180, now=now + timedelta(seconds=181)) == "STALE"
    later = AgentReport.model_validate(report(cluster.id, observed_at=now + timedelta(seconds=30)))
    receipt = await ingest_report(session, later, settings, now=now + timedelta(seconds=30))
    assert receipt.attached_incidents == 0  # Evidence sampling is capped at once/minute.
    assert await session.scalar(select(func.count()).select_from(ClusterAgentState)) == 1


async def test_missing_evidence_is_degraded_and_resolved_incidents_are_untouched(
    api_client, agent_inventory, session
):
    cluster, _, incident = agent_inventory
    incident.state = IncidentState.RESOLVED
    await session.commit()
    payload = report(cluster.id)
    payload["workloads"][0].update(
        deployment=None, telemetry=[], errors=["KUBERNETES_COLLECTION_FAILED"]
    )
    response = await api_client.post(
        "/api/v1/agent/reports", json=payload, headers={"Authorization": f"Bearer {AGENT_TOKEN}"}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["attached_incidents"] == 0
    assert await session.scalar(select(func.count()).select_from(EvidenceSnapshot)) == 0


def test_report_strict_shape_rejects_unbounded_or_fake_observations():
    data = report(uuid.uuid4())
    data["workloads"][0].update(deployment=None, errors=[])
    with pytest.raises(ValueError, match="collection error"):
        AgentReport.model_validate(data)
    data = report(uuid.uuid4())
    data["workloads"][0]["telemetry"][0]["samples"] *= 11
    with pytest.raises(ValueError, match="oversized"):
        AgentReport.model_validate_json(json.dumps(data))


async def test_agent_collect_publish_persist_and_read_operational_loop(
    api_client, agent_inventory, viewer_headers, monkeypatch
):
    cluster, _, incident = agent_inventory
    settings = AgentSettings(
        cluster_id=cluster.id,
        control_plane_url="https://cloudward.example",
        token=AGENT_TOKEN,
        targets=[
            {
                "namespace": "cloudward-staging",
                "service": "cloudward-demo",
                "deployment": "cloudward-demo",
            }
        ],
    )

    def kubernetes_api(request):
        if "/deployments/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "metadata": {"generation": 2},
                    "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "cloudward-demo"}}},
                    "status": {"observedGeneration": 2, "readyReplicas": 1, "updatedReplicas": 2},
                },
            )
        return httpx.Response(200, json={"metadata": {}, "items": []})

    async with httpx.AsyncClient(
        base_url="https://kubernetes.default.svc", transport=httpx.MockTransport(kubernetes_api)
    ) as kube_client:
        collector = AgentCollector(
            settings, KubernetesReader(kube_client, lambda: "test-projected-token", 1)
        )
        monkeypatch.setattr(
            collector.metrics,
            "_get",
            AsyncMock(
                return_value={
                    "status": "success",
                    "data": {"result": [{"metric": {}, "values": [[1, "1"]]}]},
                }
            ),
        )
        monkeypatch.setattr(
            collector.logs,
            "_get",
            AsyncMock(
                return_value={
                    "status": "success",
                    "data": {
                        "result": [{"stream": {}, "values": [["1", "password=redact-at-source"]]}]
                    },
                }
            ),
        )
        monkeypatch.setattr(
            collector.traces, "_get", AsyncMock(return_value={"traces": [{"traceID": "trace-1"}]})
        )
        monkeypatch.setattr(
            collector.cost,
            "workload_allocation",
            AsyncMock(return_value=CostAllocation(total_cost=1.25)),
        )
        collected = await collector.collect()
    assert not collected.workloads[0].errors
    assert "redact-at-source" not in collected.model_dump_json()
    assert await ReportPublisher(settings, api_client).publish(collected)
    response = await api_client.get(
        f"/api/v1/observability/incidents/{incident.id}/evidence", headers=viewer_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 7
    assert {item["evidence_type"] for item in response.json()} == {
        "KUBERNETES_STATE",
        "METRIC_SUMMARY",
        "LOG_SUMMARY",
        "TRACE_SUMMARY",
        "FINOPS",
    }
    assert all(item["payload"]["report_id"] == str(collected.report_id) for item in response.json())
