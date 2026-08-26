"""Incident persistence operations that preserve state history."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import record_audit
from app.db.base import utc_now
from app.db.models import ActionProposal, ActorType, Environment, Incident, IncidentEvent
from app.errors import CloudWardError
from app.events import append_stream_event
from app.incidents.state_machine import IncidentState, transition_incident
from app.metrics import ACTIVE_INCIDENTS, INCIDENTS_TOTAL


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
) -> Incident:
    previous = incident.state
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
        from app.notifications import queue_incident_notification
        from app.tasks import create_task_publisher

        settings = get_settings()
        await queue_incident_notification(
            session,
            settings,
            event_type=notification_event,
            incident=incident,
            details=details,
            publisher=create_task_publisher(settings),
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
