"""Single-decision approval workflow bound to proposal and live target state."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.auth.schemas import Principal
from app.config import Settings
from app.db.base import utc_now
from app.db.models import (
    ActionExecution,
    ActionProposal,
    ActorType,
    Approval,
    ApprovalDecision,
    Incident,
    PolicyDecision,
    RecordStatus,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.incidents.state_machine import IncidentState
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.policies.opa import ApprovalInput, PolicyInput, TargetInput
from app.rbac import has_permission
from app.remediation.actions import get_action_metadata
from app.risk.engine import RiskFactors


def _context(
    incident: Incident,
    proposal: ActionProposal,
    *,
    proposal_version: int,
) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "incident_state": IncidentState.AWAITING_APPROVAL.value,
        "proposal_id": str(proposal.id),
        "proposal_version": proposal_version,
        "action": proposal.action_type.value,
        "risk_score": proposal.risk_score,
        "parameters": proposal.parameters,
    }


def _digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _target_reference(parameters: dict[str, Any]) -> str:
    namespace = str(parameters.get("namespace", "unknown"))
    name = str(
        parameters.get("deployment")
        or parameters.get("pod_name")
        or parameters.get("pod")
        or "unknown"
    )
    return f"{namespace}/{name}"


async def ensure_runtime_approval(
    session: AsyncSession,
    *,
    incident: Incident,
    proposal: ActionProposal,
    settings: Settings,
    requested_by: str,
    reason: str | None,
) -> Approval:
    existing = (
        await session.execute(
            select(Approval).where(
                Approval.proposal_id == proposal.id,
                Approval.proposal_version == 1,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    metadata = get_action_metadata(proposal.action_type)
    context = _context(incident, proposal, proposal_version=1)
    approval = Approval(
        incident_id=incident.id,
        proposal_id=proposal.id,
        actor_id=None,
        decision=ApprovalDecision.PENDING,
        reason=reason,
        action=proposal.action_type.value,
        environment=incident.environment,
        risk_score=proposal.risk_score,
        blast_radius=max(1, int(proposal.parameters.get("target_count", 1))),
        reversible=metadata.reversible,
        requested_by=requested_by,
        runbook=incident.runbook_id,
        proposal_version=1,
        target_reference=_target_reference(proposal.parameters),
        expected_state=context,
        context_digest=_digest(context),
        expires_at=utc_now() + timedelta(seconds=settings.approval_ttl_seconds),
    )
    session.add(approval)
    await session.flush()
    await record_audit(
        session,
        event_type="APPROVAL_REQUESTED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        actor=requested_by,
        action=proposal.action_type.value,
        risk_score=proposal.risk_score,
        policy_decision="APPROVAL_REQUIRED",
        result="PENDING",
        metadata={
            "approval_id": str(approval.id),
            "proposal_id": str(proposal.id),
            "proposal_version": approval.proposal_version,
            "target_reference": approval.target_reference,
            "expires_at": approval.expires_at.isoformat(),
            "reason": reason,
        },
    )
    await _stream(session, approval)
    return approval


class ApprovalService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        kubernetes: KubernetesExecutor,
        opa: OPAClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.kubernetes = kubernetes
        self.opa = opa

    async def decide(
        self,
        approval_id: uuid.UUID,
        *,
        decision: ApprovalDecision,
        principal: Principal,
        comment: str | None,
    ) -> Approval:
        if decision not in {ApprovalDecision.APPROVED, ApprovalDecision.REJECTED}:
            raise CloudWardError("INVALID_APPROVAL_DECISION", "Decision must approve or reject")
        approval = (
            await self.session.execute(
                select(Approval).where(Approval.id == approval_id).with_for_update()
            )
        ).scalar_one_or_none()
        if approval is None:
            raise CloudWardError("APPROVAL_NOT_FOUND", "Approval was not found", status_code=404)
        if approval.decision != ApprovalDecision.PENDING:
            raise CloudWardError(
                "APPROVAL_ALREADY_DECIDED",
                "Approval has already been decided and cannot execute twice",
                status_code=409,
            )
        incident = await self.session.get(Incident, approval.incident_id, with_for_update=True)
        proposal = await self.session.get(ActionProposal, approval.proposal_id, with_for_update=True)
        if incident is None or proposal is None:
            await self._invalidate(approval, "Bound incident or proposal no longer exists")
            raise CloudWardError("APPROVAL_CONTEXT_MISSING", "Approval context no longer exists", status_code=409)

        if decision == ApprovalDecision.REJECTED:
            proposal.status = RecordStatus.REJECTED
            approval.decision = ApprovalDecision.REJECTED
            approval.actor_id = principal.user_id if principal.persisted else None
            approval.decided_by = principal.login
            approval.decided_at = utc_now()
            approval.decision_comment = comment
            await self._move_incident(
                incident,
                IncidentState.BLOCKED,
                actor=principal.login,
                approval=approval,
            )
            await self._audit_decision(approval, incident, principal, "REJECTED")
            await _stream(self.session, approval)
            return approval

        metadata = get_action_metadata(proposal.action_type)
        if not has_permission(principal.role, metadata.required_permission):
            raise CloudWardError(
                "APPROVAL_ROLE_INSUFFICIENT",
                "This action requires an administrator-level approval",
                status_code=403,
            )
        if proposal.risk_score >= 70:
            raise CloudWardError(
                "HIGH_RISK_ACTION_BLOCKED",
                "Actions scoring 70 or higher cannot be approved",
                status_code=403,
            )
        stale_reason = await self._stale_reason(approval, incident, proposal, principal)
        if stale_reason:
            proposal.status = RecordStatus.REJECTED
            await self._invalidate(approval, stale_reason)
            if incident.state == IncidentState.AWAITING_APPROVAL:
                await self._move_incident(
                    incident,
                    IncidentState.BLOCKED,
                    actor="cloudward-approval-guard",
                    approval=approval,
                )
            await self._audit_decision(approval, incident, principal, "INVALIDATED")
            await _stream(self.session, approval)
            return approval

        approval.decision = ApprovalDecision.APPROVED
        approval.actor_id = principal.user_id if principal.persisted else None
        approval.decided_by = principal.login
        approval.decided_at = utc_now()
        approval.decision_comment = comment
        proposal.status = RecordStatus.PENDING
        await self._move_incident(
            incident,
            IncidentState.POLICY_EVALUATION,
            actor=principal.login,
            approval=approval,
        )
        await self._audit_decision(approval, incident, principal, "APPROVED")
        await _stream(self.session, approval)
        return approval

    async def _stale_reason(
        self,
        approval: Approval,
        incident: Incident,
        proposal: ActionProposal,
        principal: Principal,
    ) -> str | None:
        if approval.expires_at <= utc_now():
            return "Approval expired before decision"
        if incident.state != IncidentState.AWAITING_APPROVAL:
            return f"Incident state changed to {incident.state.value}"
        if proposal.status != RecordStatus.PENDING:
            return f"Proposal status changed to {proposal.status.value}"
        execution = (
            await self.session.execute(
                select(ActionExecution.id).where(ActionExecution.proposal_id == proposal.id).limit(1)
            )
        ).scalar_one_or_none()
        if execution is not None:
            return "Proposal already has an action execution"
        current_context = _context(
            incident,
            proposal,
            proposal_version=approval.proposal_version,
        )
        if _digest(current_context) != approval.context_digest:
            return "Proposal version, target, expected state, or risk context changed"
        target = await self._live_target(proposal)
        if target["stale_reason"]:
            return str(target["stale_reason"])
        latest_policy = (
            await self.session.execute(
                select(PolicyDecision)
                .where(PolicyDecision.proposal_id == proposal.id)
                .order_by(PolicyDecision.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_policy is None or not latest_policy.requires_approval:
            return "Policy context no longer requires this approval"
        try:
            risk_factors = RiskFactors.model_validate(proposal.risk_calculation["factors"])
        except (KeyError, ValueError):
            return "Stored risk factors are invalid"
        policy = await self.opa.evaluate(
            PolicyInput(
                environment=incident.environment.value,
                action=proposal.action_type,
                risk_score=proposal.risk_score,
                risk_factors=risk_factors,
                confidence=float(proposal.risk_calculation.get("confidence", 1.0)),
                blast_radius=max(1, approval.blast_radius),
                reversible=approval.reversible,
                service_criticality="low",
                target=TargetInput(
                    namespace=str(target["namespace"]),
                    pod_name=str(target["name"]),
                    labels=dict(target["labels"]),
                    controller_managed=bool(target["controller_managed"]),
                    target_pods=max(1, approval.blast_radius),
                ),
                approval=ApprovalInput(
                    approved=True,
                    approval_id=str(approval.id),
                    approved_by=principal.login,
                ),
            )
        )
        if not policy.allowed:
            return f"Policy no longer allows execution: {policy.reason}"
        return None

    async def _live_target(self, proposal: ActionProposal) -> dict[str, Any]:
        parameters = proposal.parameters
        namespace = parameters.get("namespace")
        if not isinstance(namespace, str):
            return {
                "namespace": "unknown",
                "name": "unknown",
                "labels": {},
                "controller_managed": False,
                "stale_reason": "Proposal has no bound namespace",
            }
        deployment_name = parameters.get("deployment")
        if isinstance(deployment_name, str):
            deployment = await self.kubernetes.get_deployment(namespace, deployment_name)
            expected_replicas = parameters.get("observed_replicas")
            if isinstance(expected_replicas, int) and deployment.desired_replicas != expected_replicas:
                return {
                    "namespace": namespace,
                    "name": deployment_name,
                    "labels": {},
                    "controller_managed": True,
                    "stale_reason": "Deployment replica state changed after proposal",
                }
            expected_tag = parameters.get("expected_current_tag")
            if isinstance(expected_tag, str) and not any(
                image.endswith(f":{expected_tag}") for image in deployment.container_images
            ):
                return {
                    "namespace": namespace,
                    "name": deployment_name,
                    "labels": {},
                    "controller_managed": True,
                    "stale_reason": "Deployment image revision changed after proposal",
                }
            pods = await self.kubernetes.get_pods(namespace, "cloudward.io/demo-target=true")
            if not pods:
                return {
                    "namespace": namespace,
                    "name": deployment_name,
                    "labels": {},
                    "controller_managed": True,
                    "stale_reason": "Deployment has no live demo target pods",
                }
            return {
                "namespace": namespace,
                "name": pods[0].name,
                "labels": pods[0].labels,
                "controller_managed": pods[0].controller_managed,
                "stale_reason": None,
            }
        pod_name = parameters.get("pod_name") or parameters.get("pod")
        if isinstance(pod_name, str):
            pod = await self.kubernetes.get_pod_health(namespace, pod_name)
            return {
                "namespace": namespace,
                "name": pod.name,
                "labels": pod.labels,
                "controller_managed": pod.controller_managed,
                "stale_reason": None,
            }
        return {
            "namespace": namespace,
            "name": "unknown",
            "labels": {},
            "controller_managed": False,
            "stale_reason": "Proposal target is not bound to a typed workload",
        }

    async def _invalidate(self, approval: Approval, reason: str) -> None:
        approval.decision = (
            ApprovalDecision.EXPIRED
            if approval.expires_at <= utc_now()
            else ApprovalDecision.INVALIDATED
        )
        approval.decided_at = utc_now()
        approval.decided_by = "cloudward-approval-guard"
        approval.invalidated_reason = reason

    async def _move_incident(
        self,
        incident: Incident,
        state: IncidentState,
        *,
        actor: str,
        approval: Approval,
    ) -> None:
        from app.incidents.service import change_incident_state

        await change_incident_state(
            self.session,
            incident,
            state,
            actor=actor,
            actor_type=ActorType.USER,
            details={
                "approval_id": str(approval.id),
                "decision": approval.decision.value,
                "proposal_version": approval.proposal_version,
            },
        )

    async def _audit_decision(
        self,
        approval: Approval,
        incident: Incident,
        principal: Principal,
        result: str,
    ) -> None:
        await record_audit(
            self.session,
            event_type=f"APPROVAL_{result}",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=principal.login,
            actor_type=ActorType.USER,
            actor_id=principal.user_id if principal.persisted else None,
            action=approval.action,
            risk_score=approval.risk_score,
            result=result,
            metadata={
                "approval_id": str(approval.id),
                "proposal_id": str(approval.proposal_id),
                "proposal_version": approval.proposal_version,
                "comment": approval.decision_comment,
                "invalidated_reason": approval.invalidated_reason,
            },
        )


async def _stream(session: AsyncSession, approval: Approval) -> None:
    await append_stream_event(
        session,
        event_type="approval.changed",
        incident_id=approval.incident_id,
        payload={
            "approval_id": str(approval.id),
            "proposal_id": str(approval.proposal_id),
            "decision": approval.decision.value,
            "action": approval.action,
            "environment": approval.environment.value,
            "risk_score": approval.risk_score,
            "expires_at": approval.expires_at.isoformat(),
            "decided_by": approval.decided_by,
            "invalidated_reason": approval.invalidated_reason,
        },
    )
