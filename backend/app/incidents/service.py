from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import record_audit
from app.db.base import utc_now
from app.db.models import (
    ActionProposal,
    ActorType,
    Environment,
    EvidencePhase,
    EvidenceSnapshot,
    Incident,
    IncidentEvent,
    ResolutionSource,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.evidence.types import EvidenceType
from app.incidents.state_machine import IncidentState, transition_incident
from app.metrics import ACTIVE_INCIDENTS, INCIDENTS_TOTAL

logger = logging.getLogger(__name__)


async def create_incident(
    session: AsyncSession,
    *,
    correlation_id: str,
    incident_type: str,
    title: str,
    environment: Environment,
    summary: str | None = None,
    service_id: uuid.UUID | None = None,
    cluster_id: uuid.UUID | None = None,
    actor: str = "cloudward",
    actor_type: ActorType = ActorType.SYSTEM,
) -> Incident:
    incident = Incident(
        correlation_id=correlation_id,
        incident_type=incident_type,
        title=title,
        summary=summary,
        environment=environment,
        service_id=service_id,
        cluster_id=cluster_id,
        state=IncidentState.DETECTED,
    )
    session.add(incident)
    INCIDENTS_TOTAL.labels(incident_type, environment.value, incident.severity).inc()
    ACTIVE_INCIDENTS.labels(environment.value).inc()
    await session.flush()
    event = IncidentEvent(
        incident_id=incident.id,
        correlation_id=correlation_id,
        event_type="INCIDENT_CREATED",
        from_state=None,
        to_state=IncidentState.DETECTED,
        actor=actor,
        actor_type=actor_type,
        details={"incident_type": incident_type},
    )
    session.add(event)
    await append_stream_event(
        session,
        event_type="incident.created",
        incident_id=incident.id,
        payload={"state": IncidentState.DETECTED.value, "incident_type": incident_type},
    )
    await record_audit(
        session,
        event_type="INCIDENT_CREATED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        actor=actor,
        actor_type=actor_type,
        result="SUCCEEDED",
        metadata={"incident_type": incident_type, "state": IncidentState.DETECTED.value},
    )
    await session.flush()
    return incident


async def change_incident_state(
    session: AsyncSession,
    incident: Incident,
    target: IncidentState,
    *,
    actor: str = "cloudward",
    actor_type: ActorType = ActorType.SYSTEM,
    details: dict[str, Any] | None = None,
    force: bool = False,
) -> Incident:
    previous = incident.state
    if previous == target:
        return incident
    if not force:
        transition_incident(previous, target)
    incident.state = target
    if target == IncidentState.RESOLVED:
        incident.resolved_at = utc_now()
    if target in {IncidentState.RESOLVED, IncidentState.BLOCKED, IncidentState.ESCALATED}:
        ACTIVE_INCIDENTS.labels(incident.environment.value).dec()
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            correlation_id=incident.correlation_id,
            event_type="STATE_CHANGED",
            from_state=previous,
            to_state=target,
            actor=actor,
            actor_type=actor_type,
            details=details or {},
        )
    )
    await append_stream_event(
        session,
        event_type="incident.state_changed",
        incident_id=incident.id,
        payload={
            "from_state": previous.value,
            "to_state": target.value,
            "state": target.value,
            **(details or {}),
        },
    )
    await record_audit(
        session,
        event_type="INCIDENT_STATE_CHANGED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        actor=actor,
        actor_type=actor_type,
        result="SUCCEEDED",
        metadata={"from_state": previous.value, "to_state": target.value, **(details or {})},
    )
    if target == IncidentState.AWAITING_APPROVAL:
        proposal = (
            await session.execute(
                select(ActionProposal)
                .where(ActionProposal.incident_id == incident.id)
                .order_by(ActionProposal.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if proposal is not None:
            from app.approvals import ensure_runtime_approval
            from app.config import get_settings

            await ensure_runtime_approval(
                session,
                incident=incident,
                proposal=proposal,
                settings=get_settings(),
                requested_by=actor,
                reason=(details or {}).get("policy_reason") or (details or {}).get("reason"),
            )
    notification_event = {
        IncidentState.AWAITING_APPROVAL: "approval_required",
        IncidentState.RESOLVED: "incident_resolved",
        IncidentState.ESCALATED: (
            "remediation_failed" if (details or {}).get("error_code") else "incident_escalated"
        ),
    }.get(target)
    if notification_event is not None:
        from app.config import get_settings

        settings = get_settings()
        if settings.app_env != "test":
            from app.notifications import queue_incident_notification
            from app.tasks import create_task_publisher

            try:
                await queue_incident_notification(
                    session,
                    settings,
                    event_type=notification_event,
                    incident=incident,
                    details=details,
                    publisher=create_task_publisher(settings),
                )
            except Exception as exc:
                # Safe degradation if broker is offline
                logger.warning(
                    "incident_notification_queue_failed",
                    extra={"fields": {"error": str(exc)}},
                )
    if target in {IncidentState.RESOLVED, IncidentState.BLOCKED, IncidentState.ESCALATED}:
        # Local import avoids coupling incident creation to Part 3 memory internals.
        from app.incident_memory.capture import capture_terminal_incident

        await capture_terminal_incident(session, incident)
    await session.flush()
    return incident


async def get_incident(session: AsyncSession, incident_id: uuid.UUID) -> Incident:
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id).options(selectinload(Incident.events))
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise CloudWardError("INCIDENT_NOT_FOUND", "Incident was not found", status_code=404)
    return incident


async def resolve_incident(
    session: AsyncSession,
    incident: Incident,
    *,
    actor: str = "cloudward",
    actor_type: ActorType = ActorType.USER,
    reason: str = "Resolved by operator",
    source: ResolutionSource = ResolutionSource.HUMAN_ACTION,
) -> Incident:
    if incident.state == IncidentState.RESOLVED:
        return incident
    incident.resolution_source = source
    incident.resolved_at = utc_now()
    return await change_incident_state(
        session,
        incident,
        IncidentState.RESOLVED,
        actor=actor,
        actor_type=actor_type,
        details={"reason": reason, "resolution_source": source.value},
        force=True,
    )


async def update_incident(
    session: AsyncSession,
    incident: Incident,
    *,
    title: str | None = None,
    summary: str | None = None,
    severity: str | None = None,
    target_state: IncidentState | None = None,
    actor: str = "cloudward",
    actor_type: ActorType = ActorType.USER,
) -> Incident:
    changes: dict[str, Any] = {}
    if title is not None and title != incident.title:
        changes["title"] = {"from": incident.title, "to": title}
        incident.title = title
    if summary is not None and summary != incident.summary:
        changes["summary"] = {"from": incident.summary, "to": summary}
        incident.summary = summary
    if severity is not None and severity != incident.severity:
        changes["severity"] = {"from": incident.severity, "to": severity}
        incident.severity = severity
    if target_state is not None and target_state != incident.state:
        await change_incident_state(
            session,
            incident,
            target_state,
            actor=actor,
            actor_type=actor_type,
            details={"reason": "Updated via incident update"},
            force=True,
        )
    if changes:
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                correlation_id=incident.correlation_id,
                event_type="INCIDENT_UPDATED",
                from_state=incident.state,
                to_state=incident.state,
                actor=actor,
                actor_type=actor_type,
                details={"changes": changes},
            )
        )
        await record_audit(
            session,
            event_type="INCIDENT_UPDATED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            result="SUCCEEDED",
            metadata={"changes": changes},
        )
    await session.flush()
    return incident


async def add_incident_evidence(
    session: AsyncSession,
    incident: Incident,
    *,
    evidence_type: EvidenceType,
    summary: str,
    payload: dict[str, Any],
    source: str = "api",
    phase: EvidencePhase = EvidencePhase.INCIDENT,
    reference: str | None = None,
    query: str | None = None,
    collected_by: str = "cloudward",
) -> EvidenceSnapshot:
    evidence = EvidenceSnapshot(
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        evidence_type=evidence_type,
        summary=summary,
        payload=payload,
        phase=phase,
        reference=reference,
        query=query,
        collected_by=collected_by,
    )
    session.add(evidence)
    await session.flush()
    await append_stream_event(
        session,
        event_type="incident.evidence_added",
        incident_id=incident.id,
        payload={"evidence_id": str(evidence.id), "evidence_type": evidence_type.value},
    )
    await record_audit(
        session,
        event_type="EVIDENCE_COLLECTED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        actor=collected_by,
        actor_type=ActorType.USER,
        result="SUCCEEDED",
        metadata={
            "evidence_id": str(evidence.id),
            "evidence_type": evidence_type.value,
            "source": source,
        },
    )
    await session.flush()
    return evidence
