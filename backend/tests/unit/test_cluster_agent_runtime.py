from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.cluster_agent.collector import AgentCollector, KubernetesReader
from app.cluster_agent.config import AgentSettings
from app.cluster_agent.health import healthy
from app.cluster_agent.runtime import ReportPublisher
from app.cluster_agent.schemas import (
    AgentReport,
    AgentTarget,
    DeploymentObservation,
    WorkloadReport,
)
from app.config import Settings
from app.finops.schemas import CostAllocation
from app.observability.providers import TelemetryResult


def config(**kwargs):
    return AgentSettings(
        cluster_id=uuid.uuid4(),
        control_plane_url="https://cloudward.example",
        token="test-agent-token-" + "a" * 32,
        targets=[AgentTarget(namespace="cloudward-staging", service="demo", deployment="demo")],
        **kwargs,
    )


def observation():
    return DeploymentObservation(
        generation=2,
        observed_generation=2,
        desired_replicas=2,
        ready_replicas=1,
        updated_replicas=2,
        pods=[],
    )


def report(settings):
    return AgentReport(
        report_id=uuid.uuid4(),
        cluster_id=settings.cluster_id,
        observed_at=datetime.now(UTC),
        workloads=[WorkloadReport(target=settings.targets[0], deployment=observation())],
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"control_plane_url": "http://cloudward.example"},
        {"control_plane_url": "https://user:secret@cloudward.example"},
        {"control_plane_url": "https://cloudward.example/path"},
        {"prometheus_url": "http://169.254.169.254"},
        {"prometheus_url": "file:///etc/passwd"},
        {"token": "short"},
    ],
)
def test_agent_settings_reject_unsafe_boundaries(changes):
    values = config().model_dump()
    values.update(changes)
    with pytest.raises(ValueError):
        AgentSettings.model_validate(values)


def test_api_requires_distinct_agent_identity():
    with pytest.raises(ValueError, match="registered cluster"):
        Settings(app_env="test", cluster_agent_enabled=True)
    with pytest.raises(ValueError, match="must not share"):
        Settings(
            app_env="test",
            cluster_agent_enabled=True,
            cluster_agent_cluster_id=uuid.uuid4(),
            cluster_agent_token="a" * 40,
            worker_internal_token="a" * 40,
        )


async def test_kubernetes_reader_only_reads_named_deployment_and_bounded_pods():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer rotating-test-token"
        if "/deployments/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "metadata": {"generation": 2, "annotations": {"secret": "never-collect"}},
                    "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "demo"}}},
                    "status": {"observedGeneration": 2, "readyReplicas": 1, "updatedReplicas": 2},
                },
            )
        assert request.url.params["limit"] == "50"
        assert request.url.params["labelSelector"] == "app=demo"
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": "next-page"},
                "items": [
                    {
                        "metadata": {"name": "demo-a"},
                        "spec": {
                            "containers": [
                                {"env": [{"name": "PASSWORD", "value": "never-collect"}]}
                            ]
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [{"restartCount": 2}],
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://kubernetes.default.svc", transport=httpx.MockTransport(handler)
    ) as client:
        reader = KubernetesReader(client, lambda: "rotating-test-token", 1)
        result = await reader.observe(config().targets[0])
    assert len(requests) == 2
    assert result.truncated
    assert result.ready_replicas == 1
    assert result.pods[0].ready
    assert result.pods[0].restarts == 2
    assert "never-collect" not in result.model_dump_json()


async def test_collector_redacts_and_exposes_partial_provider_failure(monkeypatch):
    settings = config()
    reader = AsyncMock()
    reader.observe.return_value = observation()
    collector = AgentCollector(settings, reader)

    async def result(query, window):
        return TelemetryResult(
            provider="loki", query=query, window=window, samples=[{"line": "password=never-send"}]
        )

    monkeypatch.setattr(
        collector.metrics, "query_range", AsyncMock(side_effect=TimeoutError("secret credential"))
    )
    monkeypatch.setattr(collector.logs, "query_range", result)
    monkeypatch.setattr(
        collector.traces, "search", AsyncMock(side_effect=ValueError("bad response"))
    )
    monkeypatch.setattr(
        collector.cost,
        "workload_allocation",
        AsyncMock(return_value=CostAllocation(total_cost=1.5)),
    )
    result_report = await collector.collect()
    assert result_report.workloads[0].deployment.ready_replicas == 1
    assert result_report.workloads[0].errors == [
        "PROMETHEUS_COLLECTION_FAILED",
        "TEMPO_COLLECTION_FAILED",
    ]
    assert "never-send" not in result_report.model_dump_json()
    assert "secret credential" not in result_report.model_dump_json()


@pytest.mark.parametrize("status,calls", [(202, 1), (401, 1), (302, 1), (503, 3), (429, 3)])
async def test_delivery_retries_are_bounded_and_reuse_report_identity(monkeypatch, status, calls):
    settings = config()
    payload = report(settings)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://untrusted.example"},
            json={
                "report_id": str(payload.report_id),
                "duplicate": False,
                "attached_incidents": 0,
                "status": "CONNECTED",
            },
        )

    monkeypatch.setattr("app.cluster_agent.runtime.asyncio.sleep", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        published = await ReportPublisher(settings, client).publish(payload)
    assert published is (status == 202)
    assert len(seen) == calls
    assert {request.url.host for request in seen} == {"cloudward.example"}
    assert all(request.content == seen[0].content for request in seen)


def test_health_separates_live_loop_from_successful_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_DIRECTORY", str(tmp_path))
    assert not healthy()
    state = tmp_path / "status.json"
    state.write_text(json.dumps({"cycle_at": time.time(), "delivered_at": None}))
    assert healthy(liveness=True)
    assert not healthy()
    state.write_text(json.dumps({"cycle_at": time.time(), "delivered_at": time.time()}))
    assert healthy()
    state.write_text(
        json.dumps(
            {
                "cycle_at": time.time(),
                "delivered_at": (datetime.now(UTC) - timedelta(minutes=5)).timestamp(),
            }
        )
    )
    assert not healthy()
