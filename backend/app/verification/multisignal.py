"""Multi-signal, before/after remediation verification and truthful resolution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db.models import (
    ActionExecution,
    ActorType,
    Incident,
    ResolutionSource,
    VerificationRecord,
)
from app.events import append_stream_event
from app.incidents.service import change_incident_state
from app.incidents.state_machine import IncidentState
from app.kubernetes.executor import KubernetesExecutor
from app.metrics import VERIFICATION_FAILURES_TOTAL
from app.observability import MetricsProvider, TelemetryWindow
from app.remediation.actions import ActionType


class SignalType(StrEnum):
    READY_REPLICAS = "ready_replicas"
    POD_READINESS = "pod_readiness"
    ERROR_RATE = "error_rate"
    P95_LATENCY = "p95_latency"
    RESTART_COUNT = "restart_count"
    HEALTH_ENDPOINT = "health_endpoint"
    SYNTHETIC_HTTP = "synthetic_http"


class SignalCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SignalType
    required: bool = True
    passed: bool
    before: float | int | str | bool | None = None
    after: float | int | str | bool | None = None
    threshold: float | int | str | bool | None = None
    detail: str | None = None


class MultiSignalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    checks: list[SignalCheck]
    before_values: dict[str, float | int | str | bool | None]
    after_values: dict[str, float | int | str | bool | None]


class VerificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    deployment: str
    label_selector: str
    service_name: str
    expected_replicas: int = Field(ge=1, le=20)
    error_rate_threshold: float = Field(default=0.05, ge=0, le=1)
    p95_latency_threshold_seconds: float = Field(default=2.5, ge=0.01, le=30)
    health_path: str = "health/ready"


def _latest_scalar(samples: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for series in samples:
        points = series.get("values")
        if isinstance(points, list) and points:
            point = points[-1]
            if isinstance(point, list) and len(point) == 2:
                try:
                    values.append(float(point[1]))
                except (TypeError, ValueError):
                    continue
        point = series.get("value")
        if isinstance(point, list) and len(point) == 2:
            try:
                values.append(float(point[1]))
            except (TypeError, ValueError):
                continue
    return sum(values) if values else None


class MultiSignalVerificationEngine:
    def __init__(self, *, kubernetes: KubernetesExecutor, metrics: MetricsProvider) -> None:
        self.kubernetes = kubernetes
        self.metrics = metrics

    async def verify(
        self,
        plan: VerificationPlan,
        *,
        before_values: dict[str, float | int | str | bool | None],
    ) -> MultiSignalResult:
        checks: list[SignalCheck] = []
        after: dict[str, float | int | str | bool | None] = {}
        deployment = await self.kubernetes.get_deployment(plan.namespace, plan.deployment)
        after[SignalType.READY_REPLICAS.value] = deployment.ready_replicas
        checks.append(
            SignalCheck(
                type=SignalType.READY_REPLICAS,
                passed=deployment.ready_replicas >= plan.expected_replicas,
                before=before_values.get(SignalType.READY_REPLICAS.value),
                after=deployment.ready_replicas,
                threshold=plan.expected_replicas,
            )
        )
        pods = await self.kubernetes.get_pods(plan.namespace, plan.label_selector)
        ready_pods = sum(1 for pod in pods if pod.ready)
        restart_count = sum(pod.restart_count for pod in pods)
        after[SignalType.POD_READINESS.value] = ready_pods
        after[SignalType.RESTART_COUNT.value] = restart_count
        checks.append(
            SignalCheck(
                type=SignalType.POD_READINESS,
                passed=ready_pods >= plan.expected_replicas,
                before=before_values.get(SignalType.POD_READINESS.value),
                after=ready_pods,
                threshold=plan.expected_replicas,
            )
        )
        checks.append(
            SignalCheck(
                type=SignalType.RESTART_COUNT,
                passed=True,
                before=before_values.get(SignalType.RESTART_COUNT.value),
                after=restart_count,
                required=False,
                detail="Restart count is recorded for comparison but is not a sole recovery signal",
            )
        )

        now = datetime.now(UTC)
        window = TelemetryWindow(start=now - timedelta(minutes=3), end=now, step_seconds=15)
        error_query = (
            "sum(rate(cloudward_demo_http_requests_total{"
            f'service="{plan.service_name}",status_code=~"5.."}}[2m])) '
            "/ clamp_min(sum(rate(cloudward_demo_http_requests_total{"
            f'service="{plan.service_name}"}}[2m])), 0.001)'
        )
        latency_query = (
            "histogram_quantile(0.95, sum by (le) "
            "(rate(cloudward_demo_http_request_duration_seconds_bucket{"
            f'service="{plan.service_name}"}}[2m])))'
        )
        error_rate = _latest_scalar((await self.metrics.query_range(error_query, window)).samples)
        latency = _latest_scalar((await self.metrics.query_range(latency_query, window)).samples)
        after[SignalType.ERROR_RATE.value] = error_rate
        after[SignalType.P95_LATENCY.value] = latency
        checks.append(
            SignalCheck(
                type=SignalType.ERROR_RATE,
                passed=error_rate is not None and error_rate <= plan.error_rate_threshold,
                before=before_values.get(SignalType.ERROR_RATE.value),
                after=error_rate,
                threshold=plan.error_rate_threshold,
                detail=None if error_rate is not None else "Prometheus returned no error-rate sample",
            )
        )
        checks.append(
            SignalCheck(
                type=SignalType.P95_LATENCY,
                passed=latency is not None and latency <= plan.p95_latency_threshold_seconds,
                before=before_values.get(SignalType.P95_LATENCY.value),
                after=latency,
                threshold=plan.p95_latency_threshold_seconds,
                detail=None if latency is not None else "Prometheus returned no p95 sample",
            )
        )
        health = await self.kubernetes.get_service_health(
            plan.namespace, plan.service_name, plan.health_path
        )
        after[SignalType.HEALTH_ENDPOINT.value] = health.healthy
        after[SignalType.SYNTHETIC_HTTP.value] = health.healthy
        checks.extend(
            [
                SignalCheck(
                    type=SignalType.HEALTH_ENDPOINT,
                    passed=health.healthy,
                    before=before_values.get(SignalType.HEALTH_ENDPOINT.value),
                    after=health.healthy,
                    threshold=True,
                ),
                SignalCheck(
                    type=SignalType.SYNTHETIC_HTTP,
                    passed=health.healthy,
                    before=before_values.get(SignalType.SYNTHETIC_HTTP.value),
                    after=health.healthy,
                    threshold=True,
                    detail="Synthetic request executed through the Kubernetes service proxy",
                ),
            ]
        )
        success = all(check.passed for check in checks if check.required)
        if not success:
            VERIFICATION_FAILURES_TOTAL.labels("multi_signal").inc()
        return MultiSignalResult(
            success=success,
            checks=checks,
            before_values=before_values,
            after_values=after,
        )


async def persist_verification(
    session: AsyncSession,
    *,
    incident: Incident,
    result: MultiSignalResult,
    attempt: int,
    action_execution_id: uuid.UUID | None,
    resolution_source: ResolutionSource,
) -> VerificationRecord:
    now = datetime.now(UTC)
    record = VerificationRecord(
        incident_id=incident.id,
        action_execution_id=action_execution_id,
        attempt=attempt,
        success=result.success,
        checks=[check.model_dump(mode="json") for check in result.checks],
        before_values=result.before_values,
        after_values=result.after_values,
        started_at=now,
        completed_at=now,
    )
    session.add(record)
    await session.flush()
    await append_stream_event(
        session,
        event_type="verification.progress",
        incident_id=incident.id,
        payload={
            "verification_id": str(record.id),
            "action_execution_id": str(action_execution_id) if action_execution_id else None,
            "attempt": attempt,
            "success": result.success,
            "resolution_source": resolution_source.value,
        },
    )
    action_execution = (
        await session.get(ActionExecution, action_execution_id)
        if action_execution_id is not None
        else None
    )
    if (
        not result.success
        and action_execution is not None
        and action_execution.action_type == ActionType.REVERT_IMAGE
    ):
        await record_audit(
            session,
            event_type="PERSISTENT_ROLLBACK_WITHHELD",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor="cloudward-verifier",
            actor_type=ActorType.SYSTEM,
            action=ActionType.REVERT_IMAGE.value,
            result="ESCALATION_REQUIRED",
            metadata={
                "verification_id": str(record.id),
                "reason": "automatic rollback would reintroduce the controlled bad revision",
                "approval_required": True,
            },
        )
    if result.success:
        incident.resolution_source = resolution_source
        await change_incident_state(
            session,
            incident,
            IncidentState.RESOLVED,
            actor="cloudward-verifier",
            actor_type=ActorType.SYSTEM,
            details={
                "verification_id": str(record.id),
                "resolution_source": resolution_source.value,
            },
        )
    elif attempt >= 3:
        await change_incident_state(
            session,
            incident,
            IncidentState.ESCALATED,
            actor="cloudward-verifier",
            actor_type=ActorType.SYSTEM,
            details={"verification_id": str(record.id), "reason": "attempt_limit_reached"},
        )
    return record
