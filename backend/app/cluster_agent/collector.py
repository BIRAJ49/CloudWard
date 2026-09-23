"""Read named deployments, bounded pods, and curated local telemetry; never Secrets."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from app.cluster_agent.config import AgentSettings
from app.cluster_agent.schemas import (
    AgentReport,
    AgentTarget,
    DeploymentObservation,
    PodObservation,
    WorkloadReport,
)
from app.finops.providers import OpenCostClient
from app.finops.schemas import CostAllocation
from app.observability.providers import (
    LokiLogsProvider,
    PrometheusMetricsProvider,
    TelemetryResult,
    TelemetryWindow,
    TempoTracesProvider,
)
from app.security.redaction import redact_untrusted


class WorkloadReader(Protocol):
    async def observe(self, target: AgentTarget) -> DeploymentObservation: ...


class KubernetesReader:
    def __init__(
        self, client: httpx.AsyncClient, token_reader: Callable[[], str], timeout: float
    ) -> None:
        self.client = client
        self.token_reader = token_reader
        self.timeout = timeout

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        # Read the mounted token per request so projected service-account rotation works.
        async with (
            asyncio.timeout(self.timeout),
            self.client.stream(
                "GET",
                path,
                params=params,
                headers={"Authorization": f"Bearer {self.token_reader().strip()}"},
                follow_redirects=False,
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > 1_048_576:
                    raise ValueError("Kubernetes response exceeds byte bound")
                body.extend(chunk)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Kubernetes response must be an object")
        return payload

    async def observe(self, target: AgentTarget) -> DeploymentObservation:
        deployment = await self._get(
            f"/apis/apps/v1/namespaces/{target.namespace}/deployments/{target.deployment}"
        )
        spec = deployment["spec"]
        labels = spec.get("selector", {}).get("matchLabels", {})
        if not isinstance(labels, dict) or not labels:
            raise ValueError("a bounded label selector is required")
        pods = await self._get(
            f"/api/v1/namespaces/{target.namespace}/pods",
            {
                "labelSelector": ",".join(
                    f"{key}={value}" for key, value in sorted(labels.items())
                ),
                "limit": "50",
            },
        )
        status = deployment.get("status", {})
        observations = []
        for pod in pods["items"][:50]:
            pod_status = pod.get("status", {})
            observations.append(
                PodObservation(
                    name=pod["metadata"]["name"],
                    phase=pod_status.get("phase", "Unknown"),
                    ready=any(
                        item.get("type") == "Ready" and item.get("status") == "True"
                        for item in pod_status.get("conditions", [])
                    ),
                    restarts=sum(
                        item.get("restartCount", 0)
                        for item in pod_status.get("containerStatuses", [])
                    ),
                )
            )
        return DeploymentObservation(
            generation=deployment["metadata"]["generation"],
            observed_generation=status.get("observedGeneration", 0),
            desired_replicas=spec.get("replicas", 1),
            ready_replicas=status.get("readyReplicas", 0),
            updated_replicas=status.get("updatedReplicas", 0),
            pods=observations,
            truncated=bool(pods.get("metadata", {}).get("continue")) or len(pods["items"]) > 50,
        )


class AgentCollector:
    def __init__(self, settings: AgentSettings, kubernetes: WorkloadReader) -> None:
        self.settings = settings
        self.kubernetes = kubernetes
        self.metrics = PrometheusMetricsProvider(
            settings.prometheus_url, timeout_seconds=settings.timeout_seconds, max_samples=5
        )
        self.logs = LokiLogsProvider(
            settings.loki_url, timeout_seconds=settings.timeout_seconds, max_samples=5
        )
        self.traces = TempoTracesProvider(
            settings.tempo_url, timeout_seconds=settings.timeout_seconds, max_samples=5
        )
        self.cost = OpenCostClient(settings.opencost_url, timeout_seconds=settings.timeout_seconds)

    async def collect(self) -> AgentReport:
        # The target count and per-target fan-out are bounded by configuration/schema.
        workloads = [await self._workload(target) for target in self.settings.targets]
        return AgentReport(
            report_id=uuid.uuid4(),
            cluster_id=self.settings.cluster_id,
            observed_at=datetime.now(UTC),
            workloads=workloads,
        )

    async def _workload(self, target: AgentTarget) -> WorkloadReport:
        end = datetime.now(UTC)
        window = TelemetryWindow(start=end - timedelta(minutes=5), end=end)
        # Fixed read-only queries: no commands, arbitrary URLs, caller-supplied queries,
        # pod exec, annotations, environment variables, or Secret resources.
        queries = (
            "sum(rate(cloudward_demo_http_requests_total{"
            f'namespace="{target.namespace}",'
            f'service="{target.service}",status_code=~"5.."}}[2m]))',
            "histogram_quantile(0.95, sum by (le) (rate(cloudward_demo_http_request_duration_seconds_bucket{"
            f'namespace="{target.namespace}",'
            f'service="{target.service}"}}[2m])))',
            f'sum(kube_pod_container_status_restarts_total{{namespace="{target.namespace}"}})',
        )
        results = await asyncio.gather(
            self.kubernetes.observe(target),
            *(self.metrics.query_range(query, window) for query in queries),
            self.logs.query_range(
                f'{{k8s_namespace_name="{target.namespace}"}} | json | service="{target.service}"',
                window,
            ),
            self.traces.search(target.service, window, namespace=target.namespace),
            self.cost.workload_allocation(
                namespace=target.namespace, deployment=target.deployment, window_seconds=300
            ),
            return_exceptions=True,
        )
        errors: list[str] = []
        telemetry: list[TelemetryResult] = []
        deployment = None
        cost = None
        providers = (
            "KUBERNETES",
            "PROMETHEUS",
            "PROMETHEUS",
            "PROMETHEUS",
            "LOKI",
            "TEMPO",
            "OPENCOST",
        )
        for provider, result in zip(providers, results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                errors.append(f"{provider}_COLLECTION_FAILED")
            elif isinstance(result, DeploymentObservation):
                deployment = result
            elif isinstance(result, TelemetryResult):
                sanitized = TelemetryResult.model_validate(
                    redact_untrusted(result.model_dump(mode="json"))
                )
                if len(sanitized.model_dump_json().encode()) > 32_768:
                    errors.append(f"{provider}_EVIDENCE_TOO_LARGE")
                else:
                    telemetry.append(sanitized)
            elif isinstance(result, CostAllocation):
                cost = result
        return WorkloadReport(
            target=target,
            deployment=deployment,
            telemetry=telemetry,
            cost=cost,
            errors=sorted(set(errors)),
        )
