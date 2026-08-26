"""Typed clients for Prometheus, Loki, and Tempo with bounded evidence queries."""

from __future__ import annotations

from datetime import datetime
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
    async def search(self, service: str, window: TelemetryWindow) -> TelemetryResult: ...


class _HTTPProvider:
    def __init__(self, base_url: str, *, timeout_seconds: float, max_samples: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_samples = max_samples

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = await client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CloudWardError(
                "TELEMETRY_PROVIDER_UNAVAILABLE",
                "An observability provider could not satisfy the bounded evidence query",
                status_code=502,
                details={"provider": type(self).__name__, "reason": type(exc).__name__},
            ) from exc
        if not isinstance(payload, dict):
            raise CloudWardError("INVALID_TELEMETRY_RESPONSE", "Telemetry response was not an object")
        return payload

    def _bounded(self, samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        sanitized = [redact(sample) for sample in samples[: self.max_samples]]
        return sanitized, len(samples) > self.max_samples


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
        raw = payload.get("data", {}).get("result", [])
        samples, truncated = self._bounded(raw if isinstance(raw, list) else [])
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
        streams = payload.get("data", {}).get("result", [])
        flattened: list[dict[str, Any]] = []
        if isinstance(streams, list):
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                labels = stream.get("stream", {})
                values = stream.get("values", [])
                for value in values if isinstance(values, list) else []:
                    if isinstance(value, list) and len(value) == 2:
                        flattened.append(
                            {"timestamp_ns": value[0], "line": value[1], "labels": labels}
                        )
        samples, truncated = self._bounded(flattened)
        return TelemetryResult(
            provider="loki",
            query=query,
            window=window,
            samples=samples,
            truncated=truncated,
            reference=f"{self.base_url}/loki/api/v1/query_range",
        )


class TempoTracesProvider(_HTTPProvider):
    async def search(self, service: str, window: TelemetryWindow) -> TelemetryResult:
        query = f'{{ resource.service.name = "{service}" }}'
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
