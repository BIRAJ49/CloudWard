"""Capture terminal incident outcomes as bounded structured memory."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIDiagnosisRecord
from app.db.models import (
    ActionExecution,
    ActionProposal,
    AlertRecord,
    EvidenceSnapshot,
    Incident,
    Service,
    VerificationRecord,
)
from app.incident_memory.fingerprint import select_stable_labels
from app.incident_memory.models import IncidentMemoryRecord
from app.incident_memory.schemas import MemoryWrite
from app.incident_memory.service import IncidentMemoryService


async def capture_terminal_incident(
    session: AsyncSession,
    incident: Incident,
) -> None:
    service = await session.get(Service, incident.service_id) if incident.service_id else None
    alert = (
        await session.execute(
            select(AlertRecord)
            .where(AlertRecord.incident_id == incident.id)
            .order_by(AlertRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    diagnosis = (
        await session.execute(
            select(AIDiagnosisRecord)
            .where(AIDiagnosisRecord.incident_id == incident.id)
            .order_by(AIDiagnosisRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    execution = (
        await session.execute(
            select(ActionExecution)
            .where(ActionExecution.incident_id == incident.id)
            .order_by(ActionExecution.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    proposal = (
        await session.execute(
            select(ActionProposal)
            .where(ActionProposal.incident_id == incident.id)
            .order_by(ActionProposal.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    verification = (
        await session.execute(
            select(VerificationRecord)
            .where(VerificationRecord.incident_id == incident.id)
            .order_by(VerificationRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    evidence = list(
        (
            await session.execute(
                select(EvidenceSnapshot)
                .where(EvidenceSnapshot.incident_id == incident.id)
                .order_by(EvidenceSnapshot.created_at.desc())
                .limit(12)
            )
        ).scalars()
    )
    existing_memory = (
        await session.execute(
            select(IncidentMemoryRecord).where(IncidentMemoryRecord.incident_id == incident.id)
        )
    ).scalar_one_or_none()
    terminal_at = (
        incident.resolved_at
        or (existing_memory.resolved_at if existing_memory else None)
        or datetime.now(UTC)
    )
    start = incident.created_at
    if start.tzinfo is None and terminal_at.tzinfo is not None:
        start = start.replace(tzinfo=UTC)
    elif start.tzinfo is not None and terminal_at.tzinfo is None:
        terminal_at = terminal_at.replace(tzinfo=UTC)
    duration_seconds = max(0, int((terminal_at - start).total_seconds()))
    action = execution.action_type if execution else proposal.action_type if proposal else None
    service_key = service.name if service else alert.service if alert else "unassigned"
    namespace = service.namespace if service else alert.namespace if alert else None
    result = incident.state.value
    await IncidentMemoryService(session).remember(
        MemoryWrite(
            incident_id=incident.id,
            service=service_key,
            environment=incident.environment.value,
            incident_type=incident.incident_type,
            alert_name=alert.alert_name if alert else incident.title,
            namespace=namespace,
            root_cause_category=(
                diagnosis.root_cause_category if diagnosis else incident.incident_type
            ),
            labels=select_stable_labels(
                service.labels if service else alert.labels if alert else {}
            ),
            runbook_id=incident.runbook_id,
            action=action,
            result=result,
            verification_success=verification.success if verification else None,
            duration_seconds=duration_seconds,
            model=diagnosis.model if diagnosis else None,
            confidence=diagnosis.confidence if diagnosis else None,
            resolved_at=terminal_at,
            evidence_summary={
                "items": [
                    {
                        "type": item.evidence_type.value,
                        "summary": item.summary,
                        "reference": item.reference,
                        "phase": item.phase.value,
                    }
                    for item in evidence
                ],
                "verification": {
                    "success": verification.success,
                    "checks": verification.checks[:10],
                }
                if verification
                else None,
                "execution_status": execution.status.value if execution else None,
            },
            operator_summary=(
                f"{incident.title}; terminal state {result}; "
                f"action {action.value if action else 'none'}; "
                f"verification {verification.success if verification else 'not recorded'}"
            ),
        ),
        correlation_id=incident.correlation_id,
    )
