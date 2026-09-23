"""Idempotent alert grouping and incident correlation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.schemas import NormalizedAlert
from app.audit import record_audit
from app.db.base import utc_now
from app.db.models import ActorType, AlertRecord, AlertStatus, Incident, IncidentEvent
from app.incidents.service import create_incident
from app.incidents.state_machine import IncidentState

ALERT_INCIDENT_TYPES = {
    "HighHTTPErrorRate": "reliability.bad-deployment",
    "HighCPUSaturation": "reliability.cpu-saturation",
    "ContainerOOMKilled": "reliability.memory-pressure",
    "WorkloadUnavailable": "reliability.platform-self-healing",
}
TERMINAL_STATES = {
    IncidentState.RESOLVED,
    IncidentState.BLOCKED,
    IncidentState.ESCALATED,
}


@dataclass(frozen=True, slots=True)
class AlertIngestionResult:
    alert_id: str
    incident_id: str | None
    duplicate: bool
    created_incident: bool
    status: str


async def ingest_alerts(
    session: AsyncSession,
    alerts: list[NormalizedAlert],
    *,
    correlation_id: str,
) -> list[AlertIngestionResult]:
    results = [await _ingest_one(session, alert, correlation_id=correlation_id) for alert in alerts]
    await session.flush()
    return results


async def _ingest_one(
    session: AsyncSession,
    alert: NormalizedAlert,
    *,
    correlation_id: str,
) -> AlertIngestionResult:
    existing = (
        await session.execute(
            select(AlertRecord)
            .where(
                AlertRecord.source == alert.source,
                AlertRecord.fingerprint == alert.fingerprint,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and existing.payload_digest == alert.payload_digest:
        existing.last_received_at = utc_now()
        existing.repeat_count += 1
        await record_audit(
            session,
            event_type="ALERT_DEDUPLICATED",
            correlation_id=correlation_id,
            incident_id=existing.incident_id,
            actor_type=ActorType.SERVICE,
            result="SUCCEEDED",
            metadata={"fingerprint": alert.fingerprint, "repeat_count": existing.repeat_count},
        )
        return AlertIngestionResult(
            alert_id=str(existing.id),
            incident_id=str(existing.incident_id) if existing.incident_id else None,
            duplicate=True,
            created_incident=False,
            status=existing.status.value,
        )

    incident: Incident | None = None
    if existing is not None and existing.incident_id is not None:
        incident = await session.get(Incident, existing.incident_id)
    created_incident = False
    if alert.status == AlertStatus.FIRING and (
        incident is None or incident.state in TERMINAL_STATES
    ):
        incident = await create_incident(
            session,
            correlation_id=correlation_id,
            incident_type=ALERT_INCIDENT_TYPES.get(
                alert.alert_name, "reliability.prometheus-alert"
            ),
            title=f"{alert.alert_name} on {alert.service}",
            summary=(alert.annotations.get("summary") or alert.annotations.get("description")),
            environment=alert.environment,
            actor="alertmanager",
            actor_type=ActorType.SERVICE,
        )
        incident.severity = alert.severity
        if alert.severity.lower() == "critical":
            from app.config import get_settings
            from app.notifications import queue_incident_notification
            from app.tasks import create_task_publisher

            settings = get_settings()
            await queue_incident_notification(
                session,
                settings,
                event_type="critical_incident_detected",
                incident=incident,
                details={"service": alert.service, "cause": alert.annotations.get("summary")},
                publisher=create_task_publisher(settings),
            )
        created_incident = True

    if existing is None:
        existing = AlertRecord(
            incident_id=incident.id if incident else None,
            source=alert.source,
            fingerprint=alert.fingerprint,
            payload_digest=alert.payload_digest,
            alert_name=alert.alert_name,
            status=alert.status,
            severity=alert.severity,
            service=alert.service,
            environment=alert.environment,
            namespace=alert.namespace,
            labels=alert.labels,
            annotations=alert.annotations,
            starts_at=alert.starts_at,
            ends_at=alert.ends_at,
            last_received_at=utc_now(),
            repeat_count=1,
        )
        session.add(existing)
        await session.flush()
    else:
        existing.incident_id = incident.id if incident else existing.incident_id
        existing.payload_digest = alert.payload_digest
        existing.status = alert.status
        existing.severity = alert.severity
        existing.labels = alert.labels
        existing.annotations = alert.annotations
        existing.ends_at = alert.ends_at
        existing.last_received_at = utc_now()
        existing.repeat_count += 1

    if incident is not None:
        event_type = "ALERT_RECEIVED" if alert.status == AlertStatus.FIRING else "ALERT_RESOLVED"
        event_details: dict[str, Any] = {
            "alert_id": str(existing.id),
            "alert_name": alert.alert_name,
            "fingerprint": alert.fingerprint,
            "service": alert.service,
            "status": alert.status.value,
        }
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                correlation_id=correlation_id,
                event_type=event_type,
                from_state=incident.state,
                to_state=incident.state,
                actor="alertmanager",
                actor_type=ActorType.SERVICE,
                details=event_details,
            )
        )
        await record_audit(
            session,
            event_type=event_type,
            correlation_id=correlation_id,
            incident_id=incident.id,
            actor="alertmanager",
            actor_type=ActorType.SERVICE,
            result="SUCCEEDED",
            metadata=event_details,
        )
    return AlertIngestionResult(
        alert_id=str(existing.id),
        incident_id=str(incident.id) if incident else None,
        duplicate=False,
        created_incident=created_incident,
        status=alert.status.value,
    )
