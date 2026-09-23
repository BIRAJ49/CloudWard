"""Typed clients for Prometheus, Loki, and Tempo with bounded evidence queries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import datetime
from itertools import islice
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import CloudWardError
from app.logging import redact


class TelemetryWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime
    end: datetime
    step_seconds: int = Field(default=15, ge=1, le=300)

    @model_validator(mode="after")
    def bounded(self) -> TelemetryWindow:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("telemetry timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("telemetry window end must be after start")
        if (self.end - self.start).total_seconds() > 3600:
            raise ValueError("telemetry evidence window cannot exceed one hour")
        return self


class TelemetryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    query: str
    window: TelemetryWindow
    samples: list[dict[str, Any]]
    truncated: bool = False
    reference: str | None = None


class MetricsProvider(Protocol):
    async def query_range(self, query: str, window: TelemetryWindow) -> TelemetryResult: ...


class LogsProvider(Protocol):
    async def query_range(self, query: str, window: TelemetryWindow) -> TelemetryResult: ...


class TracesProvider(Protocol):
    async def search(
        self, service: str, window: TelemetryWindow, *, namespace: str
    ) -> TelemetryResult: ...


class _HTTPProvider:
    MAX_RESPONSE_BYTES = 1_048_576

    def __init__(self, base_url: str, *, timeout_seconds: float, max_samples: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_samples = max_samples

    async def _get(self, path: str, params: dict[str, str | int | float]) -> dict[str, Any]:
        try:
            async with (
                asyncio.timeout(self.timeout_seconds),
                httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=httpx.Timeout(self.timeout_seconds),
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
            ):
                async with client.stream("GET", path, params=params) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.MAX_RESPONSE_BYTES:
                            raise ValueError("telemetry response exceeds byte limit")
                        body.extend(chunk)
                    payload = json.loads(body)
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            raise CloudWardError(
                "TELEMETRY_PROVIDER_UNAVAILABLE",
                "An observability provider could not satisfy the bounded evidence query",
                status_code=502,
                details={"provider": type(self).__name__, "reason": type(exc).__name__},
            ) from exc
        if not isinstance(payload, dict):
            raise CloudWardError(
                "INVALID_TELEMETRY_RESPONSE", "Telemetry response was not an object"
            )
        return payload

    def _bounded(self, samples: Iterable[Any]) -> tuple[list[dict[str, Any]], bool]:
        bounded = list(islice((s for s in samples if isinstance(s, dict)), self.max_samples + 1))
        sanitized = [redact(sample) for sample in bounded[: self.max_samples]]
        return sanitized, len(bounded) > self.max_samples

    @staticmethod
    def _result(payload: dict[str, Any]) -> list[Any]:
        data = payload.get("data")
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, list):
            raise CloudWardError("INVALID_TELEMETRY_RESPONSE", "Telemetry result was not a list")
        return result


class PrometheusMetricsProvider(_HTTPProvider):
    async def query_range(self, query: str, window: TelemetryWindow) -> TelemetryResult:
        payload = await self._get(
            "/api/v1/query_range",
            {
                "query": query,
                "start": window.start.timestamp(),
                "end": window.end.timestamp(),
                "step": window.step_seconds,
            },
        )
        if payload.get("status") != "success":
            raise CloudWardError("INVALID_TELEMETRY_RESPONSE", "Prometheus rejected the query")
        samples, truncated = self._bounded(self._result(payload))
        return TelemetryResult(
            provider="prometheus",
            query=query,
            window=window,
            samples=samples,
            truncated=truncated,
            reference=f"{self.base_url}/graph",
        )


class LokiLogsProvider(_HTTPProvider):
    async def query_range(self, query: str, window: TelemetryWindow) -> TelemetryResult:
        payload = await self._get(
            "/loki/api/v1/query_range",
            {
                "query": query,
                "start": str(int(window.start.timestamp() * 1_000_000_000)),
                "end": str(int(window.end.timestamp() * 1_000_000_000)),
                "limit": self.max_samples + 1,
                "direction": "backward",
            },
        )
        if payload.get("status") != "success":
            raise CloudWardError("INVALID_TELEMETRY_RESPONSE", "Loki rejected the query")
        streams = self._result(payload)
        samples, truncated = self._bounded(
            {"timestamp_ns": value[0], "line": value[1], "labels": stream.get("stream", {})}
            for stream in streams
            if isinstance(stream, dict) and isinstance(stream.get("values"), list)
            for value in stream["values"]
            if isinstance(value, list) and len(value) == 2
        )
        return TelemetryResult(
            provider="loki",
            query=query,
            window=window,
            samples=samples,
            truncated=truncated,
            reference=f"{self.base_url}/loki/api/v1/query_range",
        )


class TempoTracesProvider(_HTTPProvider):
    async def search(
        self, service: str, window: TelemetryWindow, *, namespace: str
    ) -> TelemetryResult:
        query = (
            f"{{ resource.service.name = {json.dumps(service)}"
            f" && resource.k8s.namespace.name = {json.dumps(namespace)} }}"
        )
        payload = await self._get(
            "/api/search",
            {
                "q": query,
                "start": int(window.start.timestamp()),
                "end": int(window.end.timestamp()),
                "limit": self.max_samples + 1,
            },
        )
        traces = payload.get("traces", [])
        samples, truncated = self._bounded(traces if isinstance(traces, list) else [])
        return TelemetryResult(
            provider="tempo",
            query=query,
            window=window,
            samples=samples,
            truncated=truncated,
            reference=f"{self.base_url}/api/search",
        )
