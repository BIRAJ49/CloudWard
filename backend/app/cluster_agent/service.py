"""Authenticated observations may add evidence, never grant authority or resolve incidents."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.cluster_agent.models import ClusterAgentState
from app.cluster_agent.schemas import AgentReceipt, AgentReport, WorkloadReport
from app.config import Settings
from app.db.models import Cluster, EvidenceSnapshot, Incident, Service
from app.errors import CloudWardError
from app.events import append_stream_event
from app.evidence.types import EvidenceType
from app.incidents.state_machine import IncidentState
from app.security.redaction import redact_text, redact_untrusted

COLLECTOR = "cloudward-cluster-agent"
TERMINAL_STATES = (IncidentState.RESOLVED,)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def connection_status(
    state: ClusterAgentState, *, max_age: int, now: datetime | None = None
) -> str:
    current = now or datetime.now(UTC)
    age = (current - aware(state.observed_at)).total_seconds()
    return state.status if -30 <= age <= max_age else "STALE"


async def ingest_report(
    session: AsyncSession, report: AgentReport, settings: Settings, *, now: datetime | None = None
) -> AgentReceipt:
    current = now or datetime.now(UTC)
    if report.cluster_id != settings.cluster_agent_cluster_id:
        raise CloudWardError(
            "AGENT_CLUSTER_DENIED",
            "Agent identity is not authorized for this cluster",
            status_code=403,
        )
    age = (current - report.observed_at).total_seconds()
    if not -30 <= age <= settings.cluster_agent_freshness_seconds:
        raise CloudWardError(
            "AGENT_REPORT_STALE", "Report is stale or its clock is ahead", status_code=422
        )
    # Serializes first contact as well as subsequent reports on PostgreSQL.
    cluster = await session.scalar(
        select(Cluster).where(Cluster.id == report.cluster_id).with_for_update()
    )
    if cluster is None:
        raise CloudWardError(
            "CLUSTER_NOT_FOUND", "Register the cluster before enabling its agent", status_code=404
        )
    state = await session.get(ClusterAgentState, cluster.id)
    digest = hashlib.sha256(report.model_dump_json().encode()).hexdigest()
    if state is not None and state.report_id == report.report_id:
        if state.report_digest != digest:
            raise CloudWardError(
                "AGENT_REPORT_CONFLICT",
                "Report ID was reused with different content",
                status_code=409,
            )
        return AgentReceipt(
            report_id=report.report_id,
            duplicate=True,
            attached_incidents=0,
            status="CONNECTED" if state.status == "CONNECTED" else "DEGRADED",
        )
    if state is not None:
        if report.observed_at <= aware(state.observed_at):
            raise CloudWardError(
                "AGENT_REPORT_OUT_OF_ORDER",
                "An older observation cannot replace current evidence",
                status_code=409,
            )
        if (current - aware(state.received_at)).total_seconds() < 10:
            raise CloudWardError(
                "AGENT_REPORT_RATE_LIMITED",
                "At most one report per ten seconds is accepted",
                status_code=429,
            )
    services = list(
        (await session.scalars(select(Service).where(Service.cluster_id == cluster.id))).all()
    )
    registered = {
        (service.namespace, service.name, service.deployment_name): service for service in services
    }
    for workload in report.workloads:
        target = workload.target
        if (target.namespace, target.service, target.deployment) not in registered:
            raise CloudWardError(
                "AGENT_TARGET_DENIED",
                "Agent may report only registered workload targets",
                status_code=403,
            )
    status: Literal["CONNECTED", "DEGRADED"] = (
        "DEGRADED" if any(item.errors for item in report.workloads) else "CONNECTED"
    )
    previous_status = (
        connection_status(state, max_age=settings.cluster_agent_freshness_seconds, now=current)
        if state
        else None
    )
    payload = redact_untrusted(report.model_dump(mode="json"))
    if len(json.dumps(payload).encode()) > 524_288:
        raise CloudWardError(
            "AGENT_REPORT_TOO_LARGE", "Normalized report exceeded its byte bound", status_code=413
        )
    if state is None:
        state = ClusterAgentState(cluster_id=cluster.id)
        session.add(state)
    state.report_id = report.report_id
    state.report_digest = digest
    state.observed_at = report.observed_at
    state.received_at = current
    state.status = status
    state.payload = payload
    attached = 0
    for workload in report.workloads:
        target = workload.target
        service = registered[(target.namespace, target.service, target.deployment)]
        incidents = list(
            (
                await session.scalars(
                    select(Incident)
                    .where(
                        Incident.cluster_id == cluster.id,
                        Incident.service_id == service.id,
                        Incident.state.not_in(TERMINAL_STATES),
                    )
                    .order_by(Incident.created_at.desc())
                    .limit(20)
                )
            ).all()
        )
        if not incidents:
            continue
        latest = {
            incident_id: seen_at
            for incident_id, seen_at in (
                await session.execute(
                    select(EvidenceSnapshot.incident_id, func.max(EvidenceSnapshot.created_at))
                    .where(
                        EvidenceSnapshot.incident_id.in_([item.id for item in incidents]),
                        EvidenceSnapshot.collected_by == COLLECTOR,
                    )
                    .group_by(EvidenceSnapshot.incident_id)
                )
            ).all()
        }
        for incident in incidents:
            previous = latest.get(incident.id)
            if previous is not None and (current - aware(previous)).total_seconds() < 60:
                continue
            add_incident_evidence(session, report, workload, incident, current)
            attached += 1
            await append_stream_event(
                session,
                event_type="incident.evidence_added",
                incident_id=incident.id,
                payload={"source": COLLECTOR, "report_id": str(report.report_id)},
            )
    if previous_status != status:
        await record_audit(
            session,
            event_type="CLUSTER_AGENT_STATUS_CHANGED",
            correlation_id=str(report.report_id),
            result=status,
            metadata={
                "cluster_id": str(cluster.id),
                "previous_status": previous_status,
                "status": status,
            },
        )
    await append_stream_event(
        session,
        event_type="cluster.observation",
        incident_id=None,
        payload={
            "cluster_id": str(cluster.id),
            "observed_at": report.observed_at.isoformat(),
            "status": status,
        },
    )
    await session.flush()
    return AgentReceipt(
        report_id=report.report_id, duplicate=False, attached_incidents=attached, status=status
    )


def add_incident_evidence(
    session: AsyncSession,
    report: AgentReport,
    workload: WorkloadReport,
    incident: Incident,
    now: datetime,
) -> None:
    common: dict[str, Any] = {
        "incident_id": incident.id,
        "correlation_id": incident.correlation_id,
        "collected_by": COLLECTOR,
        "created_at": now,
    }
    provenance = {
        "report_id": str(report.report_id),
        "observed_at": report.observed_at.isoformat(),
        "target": workload.target.model_dump(),
        "source": COLLECTOR,
    }
    session.add(
        EvidenceSnapshot(
            **common,
            evidence_type=EvidenceType.KUBERNETES_STATE,
            summary="Agent-observed deployment state; not an authorization or verification result",
            window_end=report.observed_at,
            payload=redact_untrusted(
                {
                    **provenance,
                    "deployment": workload.deployment.model_dump() if workload.deployment else None,
                    "collection_errors": workload.errors,
                }
            ),
        )
    )
    kinds = {
        "prometheus": EvidenceType.METRIC_SUMMARY,
        "loki": EvidenceType.LOG_SUMMARY,
        "tempo": EvidenceType.TRACE_SUMMARY,
    }
    for item in workload.telemetry:
        session.add(
            EvidenceSnapshot(
                **common,
                evidence_type=kinds[item.provider],
                summary=f"Bounded agent {item.provider} observation",
                query=redact_text(item.query),
                window_start=item.window.start,
                window_end=item.window.end,
                payload=redact_untrusted(
                    {**provenance, "samples": item.samples, "truncated": item.truncated}
                ),
            )
        )
    if workload.cost is not None:
        session.add(
            EvidenceSnapshot(
                **common,
                evidence_type=EvidenceType.FINOPS,
                summary="Agent-observed OpenCost allocation; not an estimated saving",
                window_end=report.observed_at,
                payload={**provenance, "allocation": workload.cost.model_dump(mode="json")},
            )
        )
