"""Incident-scoped evidence queries with fixed templates and explicit windows."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidencePhase, EvidenceSnapshot
from app.evidence.types import EvidenceType
from app.observability.providers import LogsProvider, MetricsProvider, TelemetryWindow, TracesProvider

SAFE_LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.:/-]{1,253}$")


class TelemetryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str = Field(min_length=1, max_length=253)
    namespace: str = Field(min_length=1, max_length=253)

    @field_validator("service", "namespace")
    @classmethod
    def safe_label_value(cls, value: str) -> str:
        if not SAFE_LABEL_VALUE.fullmatch(value):
            raise ValueError("telemetry target contains unsafe label characters")
        return value


class IncidentEvidenceService:
    """Collect only curated metric/log/trace summaries; raw telemetry stays in its backend."""

    def __init__(
        self,
        *,
        metrics: MetricsProvider,
        logs: LogsProvider,
        traces: TracesProvider,
        before_seconds: int,
        max_incident_seconds: int = 1800,
    ) -> None:
        self.metrics = metrics
        self.logs = logs
        self.traces = traces
        self.before_seconds = before_seconds
        self.max_incident_seconds = max_incident_seconds

    async def collect(
        self,
        session: AsyncSession,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        target: TelemetryTarget,
        incident_started_at: datetime,
        phase: EvidencePhase = EvidencePhase.INCIDENT,
        now: datetime | None = None,
    ) -> list[EvidenceSnapshot]:
        collected_at = now or datetime.now(UTC)
        started = incident_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        window_start = max(
            started - timedelta(seconds=self.before_seconds),
            collected_at - timedelta(seconds=self.max_incident_seconds),
        )
        window = TelemetryWindow(start=window_start, end=collected_at, step_seconds=15)
        metric_queries = {
            "http_error_rate": (
                "sum(rate(cloudward_demo_http_requests_total{"
                f'service="{target.service}",status_code=~"5.."}}[2m])) '
                "/ clamp_min(sum(rate(cloudward_demo_http_requests_total{"
                f'service="{target.service}"}}[2m])), 0.001)'
            ),
            "p95_latency": (
                "histogram_quantile(0.95, sum by (le) "
                "(rate(cloudward_demo_http_request_duration_seconds_bucket{"
                f'service="{target.service}"}}[2m])))'
            ),
            "restart_count": (
                "sum(kube_pod_container_status_restarts_total{"
                f'namespace="{target.namespace}"}})'
            ),
        }
        snapshots: list[EvidenceSnapshot] = []
        for name, query in metric_queries.items():
            result = await self.metrics.query_range(query, window)
            snapshots.append(
                self._snapshot(
                    incident_id,
                    correlation_id,
                    EvidenceType.METRIC_SUMMARY,
                    phase,
                    window,
                    query,
                    f"Bounded {name} evidence ({len(result.samples)} series)",
                    result.reference,
                    {"metric": name, "samples": result.samples, "truncated": result.truncated},
                )
            )
        # Kubernetes metadata is the indexed Loki selector. `service` and trace IDs
        # remain JSON fields parsed at query time, avoiding high-cardinality labels.
        log_query = (
            f'{{k8s_namespace_name="{target.namespace}"}} '
            f'| json | service="{target.service}"'
        )
        logs = await self.logs.query_range(log_query, window)
        snapshots.append(
            self._snapshot(
                incident_id,
                correlation_id,
                EvidenceType.LOG_SUMMARY,
                phase,
                window,
                log_query,
                f"Selected correlated logs ({len(logs.samples)} samples)",
                logs.reference,
                {"samples": logs.samples, "truncated": logs.truncated},
            )
        )
        traces = await self.traces.search(target.service, window)
        snapshots.append(
            self._snapshot(
                incident_id,
                correlation_id,
                EvidenceType.TRACE_SUMMARY,
                phase,
                window,
                traces.query,
                f"Selected trace summaries ({len(traces.samples)} traces)",
                traces.reference,
                {"samples": traces.samples, "truncated": traces.truncated},
            )
        )
        session.add_all(snapshots)
        await session.flush()
        return snapshots

    @staticmethod
    def _snapshot(
        incident_id: uuid.UUID,
        correlation_id: str,
        evidence_type: EvidenceType,
        phase: EvidencePhase,
        window: TelemetryWindow,
        query: str,
        summary: str,
        reference: str | None,
        payload: dict[str, object],
    ) -> EvidenceSnapshot:
        return EvidenceSnapshot(
            incident_id=incident_id,
            correlation_id=correlation_id,
            evidence_type=evidence_type,
            summary=summary,
            reference=reference,
            query=query,
            window_start=window.start,
            window_end=window.end,
            phase=phase,
            payload=payload,
            collected_by="cloudward-observability",
        )
