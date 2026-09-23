"""Typed, idempotent Cilium quarantine lifecycle with observable verification."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.base import utc_now
from app.db.models import (
    ActionExecution,
    ActionProposal,
    ActorType,
    ContainmentStatus,
    Incident,
    PolicyDecision,
    QuarantineRecord,
    RecordStatus,
    ResolutionSource,
    SecurityCategory,
    SecurityEvent,
    StreamEvent,
    VerificationRecord,
)
from app.errors import CloudWardError
from app.incidents.service import change_incident_state
from app.incidents.state_machine import IncidentState
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.policies.opa import ApprovalInput, PolicyInput, PolicyResult, TargetInput
from app.remediation.actions import ActionType
from app.risk.engine import RiskContext, RiskEngine, RiskResult, Sensitivity


async def apply_quarantine(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    actor: str,
    settings: Settings,
    opa: OPAClient,
    kubernetes: KubernetesExecutor,
) -> QuarantineRecord:
    event, incident = await _event_and_incident(session, event_id)
    existing = (
        (
            await session.execute(
                select(QuarantineRecord)
                .where(
                    QuarantineRecord.security_event_id == event.id,
                    QuarantineRecord.status != ContainmentStatus.REMOVED,
                )
                .order_by(QuarantineRecord.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if existing is not None and existing.status == ContainmentStatus.CONTAINED:
        return existing
    if existing is not None and existing.status == ContainmentStatus.APPLYING:
        return existing
    if incident.state in {IncidentState.BLOCKED, IncidentState.ESCALATED, IncidentState.RESOLVED}:
        raise CloudWardError(
            "INCIDENT_NOT_ACTIONABLE",
            "The security incident is in a terminal state",
            status_code=409,
        )

    pod = await kubernetes.get_pod_health(event.namespace, event.pod)
    if pod.labels.get("cloudward.io/demo-target") != "true":
        raise CloudWardError(
            "KUBERNETES_TARGET_DENIED",
            "Live quarantine target is outside the demo safety boundary",
            status_code=403,
        )
    risk, policy_input, decision = await _authorize(
        event,
        actor=actor,
        action=ActionType.APPLY_QUARANTINE,
        opa=opa,
        live_labels=pod.labels,
        controller_managed=pod.controller_managed,
    )
    proposal = await _proposal_for_apply(session, event)
    await _persist_decision(session, event, proposal, settings, policy_input, decision, risk.score)
    if not decision.allowed:
        await record_audit(
            session,
            event_type="QUARANTINE_POLICY_DENIED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=ActorType.USER,
            action=ActionType.APPLY_QUARANTINE.value,
            risk_score=risk.score,
            policy_decision="DENY",
            result="REJECTED",
            metadata={"reason": decision.reason},
        )
        await session.commit()
        raise CloudWardError("QUARANTINE_DENIED", decision.reason, status_code=403)

    quarantine_id = event.id.hex[:12]
    record = existing or QuarantineRecord(
        incident_id=incident.id,
        security_event_id=event.id,
        namespace=event.namespace,
        pod=event.pod,
        workload=event.workload,
        policy_name=f"cloudward-quarantine-{quarantine_id}",
        selector={"cloudward.io/quarantine-id": quarantine_id},
        reason=f"Contain {event.event_type.value} detected by {event.policy}",
        risk_score=risk.score,
        opa_decision="ALLOW",
        status=ContainmentStatus.APPLYING,
        verification={},
    )
    record.status = ContainmentStatus.APPLYING
    event.containment_status = ContainmentStatus.APPLYING
    session.add(record)
    if incident.state in {IncidentState.POLICY_EVALUATION, IncidentState.AWAITING_APPROVAL}:
        await change_incident_state(
            session, incident, IncidentState.EXECUTING, actor=actor, actor_type=ActorType.USER
        )
    execution = await _new_execution(
        session,
        event,
        proposal,
        action=ActionType.APPLY_QUARANTINE,
    )
    await session.flush()
    try:
        before_probe = await kubernetes.probe_controlled_security_egress(event.namespace, event.pod)
        if not before_probe.reachable:
            raise CloudWardError(
                "QUARANTINE_BASELINE_FAILED",
                "Controlled internal egress was not reachable before quarantine",
                status_code=409,
            )
        await kubernetes.apply_quarantine_policy(
            event.namespace,
            event.pod,
            quarantine_id=quarantine_id,
            incident_id=str(incident.id),
        )
        record.applied_at = utc_now()
        await change_incident_state(
            session, incident, IncidentState.VERIFYING, actor=actor, actor_type=ActorType.USER
        )
        verification = await _wait_for_containment(
            kubernetes,
            event,
            policy_name=record.policy_name,
            quarantine_id=quarantine_id,
            settings=settings,
        )
        if not verification["success"]:
            raise CloudWardError(
                "QUARANTINE_VERIFICATION_FAILED",
                "Cilium quarantine could not be verified",
                status_code=502,
            )
        record.status = ContainmentStatus.CONTAINED
        record.verification = verification
        event.containment_status = ContainmentStatus.CONTAINED
        execution.status = RecordStatus.SUCCEEDED
        execution.result = verification
        execution.completed_at = utc_now()
        proposal.status = RecordStatus.SUCCEEDED
        session.add(
            VerificationRecord(
                incident_id=incident.id,
                action_execution_id=execution.id,
                attempt=execution.attempt,
                success=True,
                checks=cast(list[dict[str, object]], verification["checks"]),
                before_values={"controlled_internal_egress_reachable": True},
                after_values={"controlled_internal_egress_reachable": False},
            )
        )
        await record_audit(
            session,
            event_type="QUARANTINE_EXECUTED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=ActorType.USER,
            action=ActionType.APPLY_QUARANTINE.value,
            risk_score=risk.score,
            policy_decision="ALLOW",
            result="SUCCEEDED",
            metadata={"policy_name": record.policy_name, "target_pods": 1},
        )
        from app.notifications import queue_incident_notification
        from app.tasks import create_task_publisher

        await queue_incident_notification(
            session,
            settings,
            event_type="security_containment_executed",
            incident=incident,
            details={
                "service": event.workload or event.pod,
                "cause": event.event_type.value,
                "policy_reason": decision.reason,
            },
            publisher=create_task_publisher(settings),
        )
        await record_audit(
            session,
            event_type="CONTAINMENT_VERIFIED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor="cloudward-verifier",
            action=ActionType.APPLY_QUARANTINE.value,
            risk_score=risk.score,
            result="SUCCEEDED",
            metadata=verification,
        )
        _publish_containment(session, event, record)
        await session.commit()
        await session.refresh(record)
        return record
    except CloudWardError as exc:
        record.status = ContainmentStatus.VERIFICATION_FAILED
        record.verification = {"success": False, "error_code": exc.code}
        event.containment_status = ContainmentStatus.VERIFICATION_FAILED
        execution.status = RecordStatus.FAILED
        execution.error_code = exc.code
        execution.completed_at = utc_now()
        if incident.state in {IncidentState.EXECUTING, IncidentState.VERIFYING}:
            await change_incident_state(
                session,
                incident,
                IncidentState.ESCALATED,
                details={"reason": "containment verification failed", "error_code": exc.code},
            )
        await record_audit(
            session,
            event_type="CONTAINMENT_VERIFICATION_FAILED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor="cloudward-verifier",
            action=ActionType.APPLY_QUARANTINE.value,
            risk_score=risk.score,
            result="FAILED",
            metadata={"error_code": exc.code},
        )
        _publish_containment(session, event, record)
        await session.commit()
        raise


async def remove_quarantine(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    actor: str,
    settings: Settings,
    opa: OPAClient,
    kubernetes: KubernetesExecutor,
) -> QuarantineRecord:
    event, incident = await _event_and_incident(session, event_id)
    record = (
        (
            await session.execute(
                select(QuarantineRecord)
                .where(QuarantineRecord.security_event_id == event.id)
                .order_by(QuarantineRecord.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if record is None:
        raise CloudWardError(
            "QUARANTINE_NOT_FOUND", "No quarantine exists for this security event", status_code=404
        )
    if record.status == ContainmentStatus.REMOVED:
        return record
    pod = await kubernetes.get_pod_health(event.namespace, event.pod)
    risk, policy_input, decision = await _authorize(
        event,
        actor=actor,
        action=ActionType.REMOVE_QUARANTINE,
        opa=opa,
        live_labels=pod.labels,
        controller_managed=pod.controller_managed,
    )
    proposal = ActionProposal(
        incident_id=incident.id,
        correlation_id=event.correlation_id,
        action_type=ActionType.REMOVE_QUARANTINE,
        parameters={
            "security_event_id": str(event.id),
            "namespace": event.namespace,
            "pod": event.pod,
            "policy_name": record.policy_name,
        },
        status=RecordStatus.PENDING,
        risk_score=risk.score,
        risk_calculation=risk.model_dump(mode="json"),
        proposed_by=actor,
    )
    session.add(proposal)
    await session.flush()
    await _persist_decision(session, event, proposal, settings, policy_input, decision, risk.score)
    if not decision.allowed:
        proposal.status = RecordStatus.REJECTED
        await session.commit()
        raise CloudWardError("QUARANTINE_REMOVAL_DENIED", decision.reason, status_code=403)
    record.status = ContainmentStatus.REMOVING
    event.containment_status = ContainmentStatus.REMOVING
    execution = await _new_execution(
        session,
        event,
        proposal,
        action=ActionType.REMOVE_QUARANTINE,
    )
    try:
        state = await kubernetes.remove_quarantine_policy(
            event.namespace,
            event.pod,
            policy_name=record.policy_name,
            quarantine_id=event.id.hex[:12],
        )
        verification = await _wait_for_release(
            kubernetes,
            event,
            policy_name=record.policy_name,
            quarantine_id=event.id.hex[:12],
            settings=settings,
            initial_state=state.to_dict(),
        )
        if not verification["success"]:
            raise CloudWardError(
                "QUARANTINE_REMOVAL_VERIFICATION_FAILED",
                "Quarantine removal could not be verified",
                status_code=502,
            )
        record.status = ContainmentStatus.REMOVED
        record.removed_at = utc_now()
        record.verification = verification
        event.containment_status = ContainmentStatus.REMOVED
        execution.status = RecordStatus.SUCCEEDED
        execution.result = verification
        execution.completed_at = utc_now()
        proposal.status = RecordStatus.SUCCEEDED
        if incident.state == IncidentState.VERIFYING:
            incident.resolution_source = ResolutionSource.CLOUDWARD_REMEDIATION
            await change_incident_state(
                session, incident, IncidentState.RESOLVED, actor=actor, actor_type=ActorType.USER
            )
        await record_audit(
            session,
            event_type="QUARANTINE_REMOVED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=ActorType.USER,
            action=ActionType.REMOVE_QUARANTINE.value,
            risk_score=risk.score,
            policy_decision="ALLOW",
            result="SUCCEEDED",
            metadata={"policy_name": record.policy_name},
        )
        _publish_containment(session, event, record)
        await session.commit()
        await session.refresh(record)
        return record
    except CloudWardError as exc:
        record.status = ContainmentStatus.VERIFICATION_FAILED
        event.containment_status = ContainmentStatus.VERIFICATION_FAILED
        execution.status = RecordStatus.FAILED
        execution.error_code = exc.code
        execution.completed_at = utc_now()
        await record_audit(
            session,
            event_type="QUARANTINE_REMOVAL_FAILED",
            correlation_id=event.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=ActorType.USER,
            action=ActionType.REMOVE_QUARANTINE.value,
            risk_score=risk.score,
            result="FAILED",
            metadata={"error_code": exc.code},
        )
        _publish_containment(session, event, record)
        await session.commit()
        raise


async def _event_and_incident(
    session: AsyncSession, event_id: uuid.UUID
) -> tuple[SecurityEvent, Incident]:
    event = (
        await session.execute(select(SecurityEvent).where(SecurityEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        raise CloudWardError(
            "SECURITY_EVENT_NOT_FOUND", "Security event was not found", status_code=404
        )
    if event.incident_id is None:
        raise CloudWardError(
            "SECURITY_EVENT_NOT_ACTIONABLE",
            "Security event has no linked incident",
            status_code=409,
        )
    incident = (
        await session.execute(select(Incident).where(Incident.id == event.incident_id))
    ).scalar_one()
    return event, incident


async def _proposal_for_apply(session: AsyncSession, event: SecurityEvent) -> ActionProposal:
    proposal = (
        (
            await session.execute(
                select(ActionProposal)
                .where(
                    ActionProposal.incident_id == event.incident_id,
                    ActionProposal.action_type == ActionType.APPLY_QUARANTINE,
                )
                .order_by(ActionProposal.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if proposal is None:
        raise CloudWardError(
            "QUARANTINE_PROPOSAL_NOT_FOUND",
            "No policy-evaluated quarantine proposal exists",
            status_code=409,
        )
    return proposal


async def _authorize(
    event: SecurityEvent,
    *,
    actor: str,
    action: ActionType,
    opa: OPAClient,
    live_labels: dict[str, str],
    controller_managed: bool,
) -> tuple[RiskResult, PolicyInput, PolicyResult]:
    sensitivity = {
        SecurityCategory.SUSPICIOUS_PROCESS: Sensitivity.LOW,
        SecurityCategory.UNEXPECTED_EGRESS: Sensitivity.MODERATE,
        SecurityCategory.PRIVILEGE_BEHAVIOR: Sensitivity.HIGH,
    }[event.event_type]
    risk = RiskEngine.calculate(
        RiskContext(
            environment=event.environment.value,
            action=action,
            target_count=1,
            reversible=True,
            confidence=0.95,
            sensitivity=sensitivity,
        )
    )
    policy_input = PolicyInput(
        environment=event.environment.value,
        action=action,
        risk_score=risk.score,
        risk_factors=risk.factors,
        confidence=0.95,
        blast_radius=1,
        reversible=True,
        service_criticality=live_labels.get("cloudward.io/criticality", "low"),
        target=TargetInput(
            namespace=event.namespace,
            pod_name=event.pod,
            labels=live_labels,
            controller_managed=controller_managed,
            target_pods=1,
        ),
        approval=ApprovalInput(approved=True, approval_id=f"manual-{event.id}", approved_by=actor),
    )
    return risk, policy_input, await opa.evaluate(policy_input)


async def _persist_decision(
    session: AsyncSession,
    event: SecurityEvent,
    proposal: ActionProposal,
    settings: Settings,
    policy_input: PolicyInput,
    decision: PolicyResult,
    risk_score: int,
) -> None:
    session.add(
        PolicyDecision(
            incident_id=event.incident_id,
            proposal_id=proposal.id,
            correlation_id=event.correlation_id,
            policy_path=settings.opa_decision_path,
            allowed=decision.allowed,
            requires_approval=decision.requires_approval,
            reason=decision.reason,
            input_digest=policy_input.digest(),
            result=decision.model_dump(mode="json"),
        )
    )
    event.risk_score = risk_score
    event.policy_decision = "ALLOW" if decision.allowed else "DENY"
    await session.flush()


async def _new_execution(
    session: AsyncSession,
    event: SecurityEvent,
    proposal: ActionProposal,
    *,
    action: ActionType,
) -> ActionExecution:
    highest = await session.scalar(
        select(func.max(ActionExecution.attempt)).where(
            ActionExecution.incident_id == event.incident_id
        )
    )
    attempt = int(highest or 0) + 1
    if attempt > 3:
        raise CloudWardError(
            "ACTION_ATTEMPT_LIMIT_REACHED",
            "The incident action attempt limit has been reached",
            status_code=409,
        )
    canonical = f"{event.incident_id}:{action.value}:{event.namespace}:{event.pod}:{attempt}"
    execution = ActionExecution(
        incident_id=event.incident_id,
        proposal_id=proposal.id,
        correlation_id=event.correlation_id,
        action_type=action,
        attempt=attempt,
        status=RecordStatus.RUNNING,
        result={},
        idempotency_key=hashlib.sha256(canonical.encode()).hexdigest(),
    )
    session.add(execution)
    await session.flush()
    return execution


async def _wait_for_containment(
    kubernetes: KubernetesExecutor,
    event: SecurityEvent,
    *,
    policy_name: str,
    quarantine_id: str,
    settings: Settings,
) -> dict[str, object]:
    deadline = time.monotonic() + settings.security_quarantine_verify_timeout_seconds
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        state = await kubernetes.get_quarantine_policy_state(
            event.namespace,
            event.pod,
            policy_name=policy_name,
            quarantine_id=quarantine_id,
        )
        probe = await kubernetes.probe_controlled_security_egress(event.namespace, event.pod)
        pod = await kubernetes.get_pod_health(event.namespace, event.pod)
        checks = [
            {"name": "cilium_policy_enforced", "passed": state.enforced},
            {"name": "target_label_matches", "passed": state.target_label_matches},
            {"name": "forbidden_egress_blocked", "passed": not probe.reachable},
            {"name": "pod_health_preserved", "passed": pod.ready},
        ]
        latest = {"success": all(bool(item["passed"]) for item in checks), "checks": checks}
        if latest["success"]:
            return latest
        await asyncio.sleep(settings.security_quarantine_verify_poll_seconds)
    return latest or {"success": False, "checks": []}


async def _wait_for_release(
    kubernetes: KubernetesExecutor,
    event: SecurityEvent,
    *,
    policy_name: str,
    quarantine_id: str,
    settings: Settings,
    initial_state: dict[str, object],
) -> dict[str, object]:
    deadline = time.monotonic() + settings.security_quarantine_verify_timeout_seconds
    latest: dict[str, object] = {"initial_policy_state": initial_state}
    while time.monotonic() < deadline:
        state = await kubernetes.get_quarantine_policy_state(
            event.namespace,
            event.pod,
            policy_name=policy_name,
            quarantine_id=quarantine_id,
        )
        probe = await kubernetes.probe_controlled_security_egress(event.namespace, event.pod)
        checks = [
            {"name": "cilium_policy_removed", "passed": not state.policy_exists},
            {"name": "target_label_removed", "passed": not state.target_label_matches},
            {"name": "controlled_egress_restored", "passed": probe.reachable},
        ]
        latest = {
            "initial_policy_state": initial_state,
            "success": all(bool(item["passed"]) for item in checks),
            "checks": checks,
        }
        if latest["success"]:
            return latest
        await asyncio.sleep(settings.security_quarantine_verify_poll_seconds)
    return latest


def _publish_containment(
    session: AsyncSession, event: SecurityEvent, record: QuarantineRecord
) -> None:
    session.add(
        StreamEvent(
            event_type="security.containment",
            incident_id=event.incident_id,
            payload={
                "type": "security.containment",
                "security_event_id": str(event.id),
                "incident_id": str(event.incident_id),
                "containment_status": record.status.value,
            },
        )
    )
