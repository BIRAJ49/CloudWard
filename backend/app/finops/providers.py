"""Bounded OpenCost and Prometheus readers for the FinOps engine."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.errors import CloudWardError
from app.finops.schemas import (
    CostAllocation,
    EvidenceWindow,
    NodeObservation,
    UsageSeries,
    WorkloadObservation,
)


def _safe_base_url(value: str, provider: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise CloudWardError(
            "FINOPS_PROVIDER_URL_INVALID",
            f"{provider} URL is not a valid HTTP endpoint",
            status_code=500,
        )
    return value.rstrip("/")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


class _BoundedJSONClient:
    def __init__(
        self,
        base_url: str,
        *,
        provider: str,
        timeout_seconds: float,
        max_response_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = _safe_base_url(base_url, provider)
        self.provider = provider
        self.timeout = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._client = client

    async def get(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False, trust_env=False
        )
        try:
            async with (
                asyncio.timeout(self.timeout),
                client.stream(
                    "GET",
                    f"{self.base_url}{path}",
                    params=params,
                    headers={"Accept": "application/json"},
                ) as response,
            ):
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared and int(declared) > self.max_response_bytes:
                    raise CloudWardError(
                        "FINOPS_PROVIDER_RESPONSE_TOO_LARGE",
                        f"{self.provider} response exceeded the configured bound",
                        status_code=502,
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self.max_response_bytes:
                        raise CloudWardError(
                            "FINOPS_PROVIDER_RESPONSE_TOO_LARGE",
                            f"{self.provider} response exceeded the configured bound",
                            status_code=502,
                        )
                    body.extend(chunk)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("root JSON value is not an object")
            return payload
        except CloudWardError:
            raise
        except (httpx.HTTPError, UnicodeError, ValueError, TimeoutError) as exc:
            raise CloudWardError(
                "FINOPS_PROVIDER_UNAVAILABLE",
                f"{self.provider} did not return a valid bounded response",
                status_code=502,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


class OpenCostClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = 1_048_576,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.http = _BoundedJSONClient(
            base_url,
            provider="OpenCost",
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            client=client,
        )

    async def workload_allocation(
        self, *, namespace: str, deployment: str, window_seconds: int
    ) -> CostAllocation:
        payload = await self.http.get(
            "/allocation/compute",
            params={
                "window": f"{max(1, math.ceil(window_seconds / 60))}m",
                "aggregate": "deployment",
                "filterNamespaces": namespace,
                "accumulate": "true",
                "includeIdle": "false",
            },
        )
        allocation = self._find_allocation(payload, namespace, deployment)
        return CostAllocation(
            total_cost=_number(allocation.get("totalCost")),
            cpu_cost=_number(allocation.get("cpuCost")),
            memory_cost=_number(allocation.get("ramCost")),
        )

    async def cluster_allocation(self, *, window_seconds: int) -> CostAllocation:
        payload = await self.http.get(
            "/allocation/compute",
            params={
                "window": f"{max(1, math.ceil(window_seconds / 60))}m",
                "aggregate": "node",
                "accumulate": "true",
                "includeIdle": "true",
            },
        )
        total = cpu = memory = 0.0
        found_total = found_cpu = found_memory = False
        for allocation in self._allocations(payload).values():
            value = _number(allocation.get("totalCost"))
            if value is not None:
                total += value
                found_total = True
            value = _number(allocation.get("cpuCost"))
            if value is not None:
                cpu += value
                found_cpu = True
            value = _number(allocation.get("ramCost"))
            if value is not None:
                memory += value
                found_memory = True
        return CostAllocation(
            total_cost=round(total, 6) if found_total else None,
            cpu_cost=round(cpu, 6) if found_cpu else None,
            memory_cost=round(memory, 6) if found_memory else None,
        )

    @staticmethod
    def _allocations(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[-1], dict):
            raise CloudWardError(
                "FINOPS_OPENCOST_DATA_MISSING",
                "OpenCost returned no allocation data for the requested window",
                status_code=409,
            )
        return {str(name): value for name, value in data[-1].items() if isinstance(value, dict)}

    def _find_allocation(
        self, payload: dict[str, Any], namespace: str, deployment: str
    ) -> dict[str, Any]:
        allocations = self._allocations(payload)
        matches = [
            value
            for name, value in allocations.items()
            if deployment in name and (namespace in name or name == deployment)
        ]
        if len(matches) != 1:
            raise CloudWardError(
                "FINOPS_OPENCOST_TARGET_AMBIGUOUS",
                "OpenCost did not return exactly one allocation for the fixed workload target",
                status_code=409,
            )
        return matches[0]


class PrometheusFinOpsClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = 1_048_576,
        max_samples: int = 1000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.http = _BoundedJSONClient(
            base_url,
            provider="Prometheus",
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            client=client,
        )
        self.max_samples = max_samples

    async def _collect_metrics(
        self,
        queries: dict[str, str],
        start: datetime,
        end: datetime,
        step_seconds: int,
        *,
        optional: frozenset[str] = frozenset(),
    ) -> tuple[UsageSeries, UsageSeries, dict[str, float | None]]:
        # The fixed catalogs contain at most eight independent requests. Await all
        # of them before returning or raising, so no provider tasks outlive this call.
        ranges = [
            asyncio.create_task(self.range_query(queries[name], start, end, step_seconds))
            for name in ("cpu_usage", "memory_usage")
        ]
        scalars = {
            name: asyncio.create_task(
                self.instant_scalar(query, end, required=name not in optional)
            )
            for name, query in queries.items()
            if name not in {"cpu_usage", "memory_usage"}
        }
        results = await asyncio.gather(*ranges, *scalars.values(), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return (
            ranges[0].result(),
            ranges[1].result(),
            {name: task.result() for name, task in scalars.items()},
        )

    async def collect_workload(
        self,
        *,
        namespace: str,
        deployment: str,
        pod_pattern: str,
        environment: str,
        window_seconds: int,
        step_seconds: int,
        allocation: CostAllocation,
    ) -> WorkloadObservation:
        end = datetime.now(UTC)
        start = end - timedelta(seconds=window_seconds)
        matcher = f'namespace="{namespace}",pod=~"{pod_pattern}"'
        queries = {
            "cpu_usage": f'max(sum by (pod) (rate(container_cpu_usage_seconds_total{{{matcher},container!="",image!=""}}[5m])))',
            "memory_usage": f'max(sum by (pod) (container_memory_working_set_bytes{{{matcher},container!="",image!=""}}))',
            "cpu_requests": f'max(sum by (pod) (kube_pod_container_resource_requests{{{matcher},resource="cpu",unit="core"}}))',
            "memory_requests": f'max(sum by (pod) (kube_pod_container_resource_requests{{{matcher},resource="memory",unit="byte"}}))',
            "cpu_limits": f'max(sum by (pod) (kube_pod_container_resource_limits{{{matcher},resource="cpu",unit="core"}}))',
            "memory_limits": f'max(sum by (pod) (kube_pod_container_resource_limits{{{matcher},resource="memory",unit="byte"}}))',
            "replicas": f'kube_deployment_spec_replicas{{namespace="{namespace}",deployment="{deployment}"}}',
        }
        cpu_usage, memory_usage, values = await self._collect_metrics(
            queries, start, end, step_seconds, optional=frozenset({"cpu_limits", "memory_limits"})
        )
        observed_seconds = self._overlap_seconds(cpu_usage, memory_usage)
        return WorkloadObservation(
            service=deployment,
            environment=environment,
            namespace=namespace,
            deployment=deployment,
            replicas=max(1, round(values["replicas"] or 0)),
            cpu_request_cores=values["cpu_requests"] or 0,
            cpu_limit_cores=values["cpu_limits"],
            memory_request_bytes=values["memory_requests"] or 0,
            memory_limit_bytes=values["memory_limits"],
            cpu_usage_cores=cpu_usage,
            memory_usage_bytes=memory_usage,
            allocation=allocation,
            window=EvidenceWindow(
                start=start,
                end=end,
                requested_seconds=window_seconds,
                observed_seconds=observed_seconds,
                sample_count=min(len(cpu_usage.values), len(memory_usage.values)),
                demo_oriented=environment != "production",
            ),
            source_queries=queries,
        )

    async def collect_nodes(
        self,
        *,
        environment: str,
        window_seconds: int,
        step_seconds: int,
        allocation: CostAllocation,
    ) -> NodeObservation:
        end = datetime.now(UTC)
        start = end - timedelta(seconds=window_seconds)
        queries = {
            "cpu_usage": 'sum(rate(node_cpu_seconds_total{mode!="idle"}[5m]))',
            "memory_usage": "sum(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)",
            "allocatable_cpu": 'sum(kube_node_status_allocatable{resource="cpu",unit="core"})',
            "allocatable_memory": 'sum(kube_node_status_allocatable{resource="memory",unit="byte"})',
            "requested_cpu": 'sum(kube_pod_container_resource_requests{resource="cpu",unit="core"})',
            "requested_memory": 'sum(kube_pod_container_resource_requests{resource="memory",unit="byte"})',
            "node_count": "count(kube_node_info)",
            "pod_count": 'count(kube_pod_info{created_by_kind!="Job"})',
        }
        cpu_usage, memory_usage, values = await self._collect_metrics(
            queries, start, end, step_seconds
        )
        return NodeObservation(
            environment=environment,
            node_count=max(1, round(values["node_count"] or 0)),
            allocatable_cpu_cores=values["allocatable_cpu"] or 0,
            allocatable_memory_bytes=values["allocatable_memory"] or 0,
            requested_cpu_cores=values["requested_cpu"] or 0,
            requested_memory_bytes=values["requested_memory"] or 0,
            cpu_usage_cores=cpu_usage,
            memory_usage_bytes=memory_usage,
            pod_count=max(0, round(values["pod_count"] or 0)),
            allocation=allocation,
            window=EvidenceWindow(
                start=start,
                end=end,
                requested_seconds=window_seconds,
                observed_seconds=self._overlap_seconds(cpu_usage, memory_usage),
                sample_count=min(len(cpu_usage.values), len(memory_usage.values)),
                demo_oriented=environment != "production",
            ),
            source_queries=queries,
        )

    async def instant_scalar(
        self, query: str, at: datetime, *, required: bool = True
    ) -> float | None:
        payload = await self.http.get(
            "/api/v1/query",
            params={"query": query, "time": str(at.timestamp())},
        )
        result = self._result(payload, expected="vector")
        if len(result) != 1:
            if not required and not result:
                return None
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_AMBIGUOUS",
                "Prometheus did not return exactly one value for a FinOps input",
                status_code=409,
            )
        value = result[0].get("value")
        if not isinstance(value, list) or len(value) != 2 or _number(value[1]) is None:
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_INVALID",
                "Prometheus returned an invalid FinOps value",
                status_code=502,
            )
        return _number(value[1])

    async def range_query(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> UsageSeries:
        payload = await self.http.get(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": str(start.timestamp()),
                "end": str(end.timestamp()),
                "step": str(step_seconds),
            },
        )
        result = self._result(payload, expected="matrix")
        if len(result) != 1:
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_AMBIGUOUS",
                "Prometheus did not return exactly one series for a FinOps input",
                status_code=409,
            )
        raw = result[0].get("values")
        if not isinstance(raw, list) or len(raw) > self.max_samples:
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_INVALID",
                "Prometheus returned a missing or oversized FinOps series",
                status_code=502,
            )
        samples: list[tuple[datetime, float]] = []
        for item in raw:
            if not isinstance(item, list) or len(item) != 2:
                continue
            timestamp = _number(item[0])
            value = _number(item[1])
            if timestamp is not None and value is not None:
                samples.append((datetime.fromtimestamp(timestamp, tz=UTC), value))
        if not samples:
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_MISSING",
                "Prometheus returned no usable samples for a FinOps input",
                status_code=409,
            )
        return UsageSeries(
            values=tuple(value for _, value in samples),
            first_timestamp=samples[0][0],
            last_timestamp=samples[-1][0],
        )

    @staticmethod
    def _result(payload: dict[str, Any], *, expected: str) -> list[dict[str, Any]]:
        data = payload.get("data")
        if payload.get("status") != "success" or not isinstance(data, dict):
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_INVALID",
                "Prometheus returned an unsuccessful FinOps query response",
                status_code=502,
            )
        if data.get("resultType") != expected or not isinstance(data.get("result"), list):
            raise CloudWardError(
                "FINOPS_PROMETHEUS_DATA_INVALID",
                "Prometheus returned an unexpected FinOps result type",
                status_code=502,
            )
        return [item for item in data["result"] if isinstance(item, dict)]

    @staticmethod
    def _overlap_seconds(first: UsageSeries, second: UsageSeries) -> int:
        first_start = first.first_timestamp
        first_end = first.last_timestamp
        second_start = second.first_timestamp
        second_end = second.last_timestamp
        if first_start is None or first_end is None or second_start is None or second_end is None:
            return 0
        start = max(first_start, second_start)
        end = min(first_end, second_end)
        return max(0, round((end - start).total_seconds()))
