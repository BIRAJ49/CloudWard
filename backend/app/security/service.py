"""Normalized Tetragon ingestion using the central incident, risk, OPA, and audit models."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.base import utc_now
from app.db.models import (
    ActionProposal,
    ActorType,
    ContainmentStatus,
    EvidenceSnapshot,
    PolicyDecision,
    RecordStatus,
    SecurityCategory,
    SecurityEvent,
    StreamEvent,
)
from app.evidence.types import EvidenceType
from app.incidents.service import change_incident_state, create_incident
from app.incidents.state_machine import IncidentState
from app.metrics import SECURITY_EVENTS_TOTAL, WEBHOOK_EVENTS_TOTAL
from app.policies import OPAClient
from app.policies.opa import PolicyInput, TargetInput
from app.remediation.actions import ActionType
from app.risk.engine import RiskContext, RiskEngine, Sensitivity
from app.security.normalization import event_fingerprint, normalized_payload
from app.security.schemas import (
    NetworkDetails,
    ProcessDetails,
    SecurityEventResponse,
    TetragonSecurityEvent,
)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    event: SecurityEvent
    duplicate: bool


def security_event_response(event: SecurityEvent) -> SecurityEventResponse:
    process_payload = event.payload.get("process")
    network_payload = event.payload.get("network")
    return SecurityEventResponse(
        id=event.id,
        event_type=event.event_type,
        severity=event.severity,
        environment=event.environment,
        namespace=event.namespace,
        pod=event.pod,
        workload=event.workload,
        container=event.container_name,
        policy=event.policy,
        evidence_ref=event.evidence_ref,
        incident_id=event.incident_id,
        containment_status=event.containment_status,
        risk_score=event.risk_score,
        policy_decision=event.policy_decision,
        occurred_at=event.occurred_at,
        last_seen_at=event.last_seen_at,
        dedup_count=event.dedup_count,
        process=ProcessDetails.model_validate(process_payload) if process_payload else None,
        network=NetworkDetails.model_validate(network_payload) if network_payload else None,
    )


async def ingest_security_event(
    session: AsyncSession,
    event: TetragonSecurityEvent,
    *,
    settings: Settings,
    opa: OPAClient,
) -> IngestionResult:
    fingerprint = event_fingerprint(event, window_seconds=settings.security_dedup_window_seconds)
    existing = (
        await session.execute(
            select(SecurityEvent).where(
                SecurityEvent.source == event.source,
                SecurityEvent.fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.dedup_count += 1
        existing.last_seen_at = utc_now()
        await record_audit(
            session,
            event_type="SECURITY_EVENT_DEDUPLICATED",
            correlation_id=existing.correlation_id,
            incident_id=existing.incident_id,
            actor="tetragon-forwarder",
            actor_type=ActorType.SERVICE,
            result="SUCCEEDED",
            metadata={"fingerprint": fingerprint, "dedup_count": existing.dedup_count},
        )
        await session.flush()
        SECURITY_EVENTS_TOTAL.labels(
            existing.event_type.value, existing.severity, "deduplicated"
        ).inc()
        WEBHOOK_EVENTS_TOTAL.labels("tetragon", "deduplicated").inc()
        return IngestionResult(event=existing, duplicate=True)

    correlation_id = f"security-{fingerprint[:24]}"
    incident = await create_incident(
        session,
        correlation_id=correlation_id,
        incident_type=f"security.{event.event_type.value.lower()}",
        title=_incident_title(event),
        summary=(
            f"Tetragon policy {event.policy} detected controlled runtime behavior in "
            f"{event.namespace}/{event.pod}."
        ),
        environment=event.environment,
        actor="tetragon-forwarder",
        actor_type=ActorType.SERVICE,
    )
    incident.severity = event.severity
    if event.severity.lower() == "critical":
        from app.notifications import queue_incident_notification
        from app.tasks import create_task_publisher

        await queue_incident_notification(
            session,
            settings,
            event_type="critical_incident_detected",
            incident=incident,
            details={"service": event.workload or event.pod, "cause": event.policy},
            publisher=create_task_publisher(settings),
        )
    incident.runbook_id = _runbook_id(event.event_type)
    incident.runbook_version = 1
    payload = normalized_payload(event)
    security_event = SecurityEvent(
        correlation_id=correlation_id,
        incident_id=incident.id,
        source=event.source,
        fingerprint=fingerprint,
        event_type=event.event_type,
        severity=event.severity,
        environment=event.environment,
        namespace=event.namespace,
        pod=event.pod,
        workload=event.workload,
        container_name=event.container,
        policy=event.policy,
        evidence_ref=event.evidence_ref,
        occurred_at=event.timestamp,
        last_seen_at=utc_now(),
        dedup_count=1,
        containment_status=ContainmentStatus.NOT_PROPOSED,
        payload=payload,
    )
    session.add(security_event)
    await session.flush()
    await record_audit(
        session,
        event_type="TETRAGON_DETECTION_RECEIVED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        actor="tetragon-forwarder",
        actor_type=ActorType.SERVICE,
        result="SUCCEEDED",
        metadata={"event_id": str(security_event.id), "policy": event.policy},
    )
    await record_audit(
        session,
        event_type="SECURITY_EVENT_NORMALIZED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        actor="cloudward-security",
        result="SUCCEEDED",
        metadata={"event_type": event.event_type.value, "fingerprint": fingerprint},
    )
    session.add(
        EvidenceSnapshot(
            incident_id=incident.id,
            correlation_id=correlation_id,
            evidence_type=EvidenceType.SECURITY_EVENT,
            summary=(
                f"{event.event_type.value} observed by {event.policy} on "
                f"{event.namespace}/{event.pod}"
            ),
            reference=event.evidence_ref,
            payload={
                "security_event_id": str(security_event.id),
                "policy": event.policy,
                "severity": event.severity,
                **payload,
            },
            collected_by="tetragon-forwarder",
        )
    )
    await change_incident_state(session, incident, IncidentState.COLLECTING_EVIDENCE)
    await change_incident_state(session, incident, IncidentState.CLASSIFYING)

    risk = RiskEngine.calculate(
        RiskContext(
            environment=event.environment.value,
            action=ActionType.APPLY_QUARANTINE,
            target_count=1,
            reversible=True,
            confidence=_diagnostic_confidence(event.event_type),
            sensitivity=_sensitivity(event),
        )
    )
    incident.risk_score = risk.score
    await record_audit(
        session,
        event_type="SECURITY_RISK_CALCULATED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        action=ActionType.APPLY_QUARANTINE.value,
        risk_score=risk.score,
        result="SUCCEEDED",
        metadata=risk.model_dump(mode="json"),
    )
    await change_incident_state(session, incident, IncidentState.ACTION_PROPOSED)
    proposal = ActionProposal(
        incident_id=incident.id,
        correlation_id=correlation_id,
        action_type=ActionType.APPLY_QUARANTINE,
        parameters={
            "security_event_id": str(security_event.id),
            "namespace": event.namespace,
            "pod": event.pod,
            "target_count": 1,
            "policy": "targeted-cilium-egress-deny",
        },
        status=RecordStatus.PENDING,
        risk_score=risk.score,
        risk_calculation=risk.model_dump(mode="json"),
        proposed_by="cloudward-security",
    )
    session.add(proposal)
    await session.flush()
    await record_audit(
        session,
        event_type="QUARANTINE_PROPOSED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        action=ActionType.APPLY_QUARANTINE.value,
        risk_score=risk.score,
        result="SUCCEEDED",
        metadata={"proposal_id": str(proposal.id), "target_pods": 1},
    )
    await change_incident_state(session, incident, IncidentState.POLICY_EVALUATION)
    labels = dict(payload.get("workload_labels") or {})
    policy_input = PolicyInput(
        environment=event.environment.value,
        action=ActionType.APPLY_QUARANTINE,
        risk_score=risk.score,
        risk_factors=risk.factors,
        confidence=_diagnostic_confidence(event.event_type),
        blast_radius=1,
        reversible=True,
        service_criticality=labels.get("cloudward.io/criticality", "low"),
        target=TargetInput(
            namespace=event.namespace,
            pod_name=event.pod,
            labels=labels,
            controller_managed=True,
            target_pods=1,
        ),
    )
    decision = await opa.evaluate(policy_input)
    decision_name = str(
        decision.model_dump(mode="json").get(
            "decision", "ALLOW" if decision.allowed else "DENY"
        )
    )
    security_event.risk_score = risk.score
    security_event.policy_decision = decision_name
    session.add(
        PolicyDecision(
            incident_id=incident.id,
            proposal_id=proposal.id,
            correlation_id=correlation_id,
            policy_path=settings.opa_decision_path,
            allowed=decision.allowed,
            requires_approval=decision.requires_approval,
            reason=decision.reason,
            input_digest=policy_input.digest(),
            result=decision.model_dump(mode="json"),
        )
    )
    await record_audit(
        session,
        event_type="SECURITY_OPA_EVALUATED",
        correlation_id=correlation_id,
        incident_id=incident.id,
        action=ActionType.APPLY_QUARANTINE.value,
        risk_score=risk.score,
        policy_decision=decision_name,
        result="SUCCEEDED",
        metadata={"requires_approval": decision.requires_approval, "reason": decision.reason},
    )
    if decision.allowed:
        security_event.containment_status = ContainmentStatus.PROPOSED
    elif decision.requires_approval:
        security_event.containment_status = ContainmentStatus.AWAITING_APPROVAL
        await change_incident_state(session, incident, IncidentState.AWAITING_APPROVAL)
    else:
        proposal.status = RecordStatus.REJECTED
        await change_incident_state(
            session,
            incident,
            IncidentState.BLOCKED,
            details={"policy_reason": decision.reason},
        )

    session.add(
        StreamEvent(
            event_type="security.event",
            incident_id=incident.id,
            payload={
                "type": "security.event",
                "security_event_id": str(security_event.id),
                "incident_id": str(incident.id),
                "event_type": security_event.event_type.value,
                "severity": security_event.severity,
                "namespace": security_event.namespace,
                "containment_status": security_event.containment_status.value,
            },
        )
    )
    await session.flush()
    SECURITY_EVENTS_TOTAL.labels(event.event_type.value, event.severity, "accepted").inc()
    WEBHOOK_EVENTS_TOTAL.labels("tetragon", "accepted").inc()
    return IngestionResult(event=security_event, duplicate=False)


def _incident_title(event: TetragonSecurityEvent) -> str:
    titles = {
        SecurityCategory.SUSPICIOUS_PROCESS: "Unexpected shell process detected",
        SecurityCategory.UNEXPECTED_EGRESS: "Unexpected internal egress detected",
        SecurityCategory.PRIVILEGE_BEHAVIOR: "Privilege-related behavior detected",
    }
    return f"{titles[event.event_type]} · {event.pod}"


def _runbook_id(category: SecurityCategory) -> str:
    return {
        SecurityCategory.SUSPICIOUS_PROCESS: "security.suspicious-shell-pattern",
        SecurityCategory.UNEXPECTED_EGRESS: "security.unexpected-egress",
        SecurityCategory.PRIVILEGE_BEHAVIOR: "security.privilege-related-behavior",
    }[category]


def _diagnostic_confidence(category: SecurityCategory) -> float:
    return {
        SecurityCategory.SUSPICIOUS_PROCESS: 0.96,
        SecurityCategory.UNEXPECTED_EGRESS: 0.94,
        SecurityCategory.PRIVILEGE_BEHAVIOR: 0.95,
    }[category]


def _sensitivity(event: TetragonSecurityEvent) -> Sensitivity:
    criticality = event.workload_labels.get("cloudward.io/criticality", "low")
    if (
        event.event_type == SecurityCategory.PRIVILEGE_BEHAVIOR
        or event.secrets_or_data_exposure
        or criticality in {"high", "critical"}
    ):
        return Sensitivity.HIGH
    if event.event_type == SecurityCategory.UNEXPECTED_EGRESS or criticality == "medium":
        return Sensitivity.MODERATE
    return Sensitivity.LOW
