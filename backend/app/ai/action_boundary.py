"""Translate an AI suggestion into a governed proposal without executing it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIDiagnosisRecord
from app.ai.redaction import redact_untrusted
from app.ai.schemas import AIActionEvaluationRequest
from app.audit import record_audit
from app.db.models import (
    ActionProposal,
    ActorType,
    Incident,
    PolicyDecision,
    RecordStatus,
    Service,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.policies import OPAClient, PolicyInput
from app.policies.opa import TargetInput
from app.remediation.actions import ActionType, get_action_metadata
from app.risk import RiskContext, RiskEngine
from app.risk.engine import Sensitivity


@dataclass(frozen=True, slots=True)
class AIActionGateResult:
    diagnosis: AIDiagnosisRecord
    proposal: ActionProposal
    decision: PolicyDecision


async def evaluate_ai_action_candidate(
    session: AsyncSession,
    *,
    incident: Incident,
    request: AIActionEvaluationRequest,
    opa: OPAClient,
    actor: str,
    actor_id: uuid.UUID,
    policy_path: str,
) -> AIActionGateResult:
    """Apply registry, deterministic risk, and OPA gates; never call an executor."""

    diagnosis = (
        await session.execute(
            select(AIDiagnosisRecord)
            .where(AIDiagnosisRecord.incident_id == incident.id)
            .order_by(AIDiagnosisRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if diagnosis is None or diagnosis.status != "AVAILABLE":
        raise CloudWardError(
            "AI_DIAGNOSIS_UNAVAILABLE",
            "An available AI diagnosis is required before evaluating a candidate",
            status_code=409,
        )
    if request.action.value not in diagnosis.action_candidates:
        raise CloudWardError(
            "AI_ACTION_NOT_SUGGESTED",
            "The selected action is not present in the latest AI diagnosis",
            status_code=422,
        )

    metadata = get_action_metadata(request.action)
    environment = incident.environment.value
    if environment not in metadata.allowed_environments:
        raise CloudWardError(
            "ACTION_ENVIRONMENT_DENIED",
            f"{request.action.value} is not allowed in {environment}",
            status_code=403,
        )

    existing = await _existing_gate_result(
        session,
        incident_id=incident.id,
        diagnosis_id=diagnosis.id,
        action=request.action,
    )
    if existing is not None:
        return AIActionGateResult(diagnosis=diagnosis, proposal=existing[0], decision=existing[1])

    service = await session.get(Service, incident.service_id) if incident.service_id else None
    namespace = request.namespace or (service.namespace if service else "default")
    resource_name = request.resource_name or (
        service.deployment_name if service else "unspecified"
    )
    labels = _bounded_labels(request.labels or (service.labels if service else {}))
    confidence = diagnosis.confidence if diagnosis.confidence is not None else 0.0
    risk = RiskEngine.calculate(
        RiskContext(
            environment=environment,
            action=request.action,
            target_count=request.target_count,
            reversible=metadata.reversible,
            confidence=confidence,
            sensitivity=Sensitivity(request.sensitivity),
        )
    )
    target = TargetInput(
        namespace=namespace,
        pod_name=resource_name,
        labels=labels,
        controller_managed=request.controller_managed,
        target_pods=request.target_count,
    )
    policy_input = PolicyInput(
        environment=environment,
        action=request.action,
        risk_score=risk.score,
        risk_factors=risk.factors,
        confidence=confidence,
        blast_radius=request.target_count,
        reversible=metadata.reversible,
        service_criticality=(service.criticality if service else "unknown"),
        target=target,
    )
    policy = await opa.evaluate(policy_input)
    parameters: dict[str, Any] = {
        "source": "ai_advisory",
        "diagnosis_id": str(diagnosis.id),
        "evidence_refs": diagnosis.evidence_refs[:20],
        "target": {
            "namespace": namespace,
            "resource_name": resource_name,
            "labels": labels,
            "target_count": request.target_count,
            "controller_managed": request.controller_managed,
        },
    }
    redacted_parameters = redact_untrusted(parameters)
    proposal = ActionProposal(
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        action_type=request.action,
        parameters=redacted_parameters if isinstance(redacted_parameters, dict) else {},
        status=(
            RecordStatus.PENDING
            if policy.allowed or policy.requires_approval
            else RecordStatus.REJECTED
        ),
        risk_score=risk.score,
        risk_calculation=risk.model_dump(mode="json"),
        proposed_by="cloudward-ai-advisory",
    )
    session.add(proposal)
    await session.flush()
    decision = PolicyDecision(
        incident_id=incident.id,
        proposal_id=proposal.id,
        correlation_id=incident.correlation_id,
        policy_path=policy_path,
        allowed=policy.allowed,
        requires_approval=policy.requires_approval,
        reason=policy.reason,
        input_digest=policy_input.digest(),
        result=policy.model_dump(mode="json"),
    )
    session.add(decision)
    event_details = {
        "diagnosis_id": str(diagnosis.id),
        "proposal_id": str(proposal.id),
        "action": request.action.value,
        "risk_score": risk.score,
        "risk_classification": risk.classification.value,
        "policy_allowed": policy.allowed,
        "requires_approval": policy.requires_approval,
        "execution_started": False,
        "advisory_only": True,
    }
    await record_audit(
        session,
        event_type="AI_ACTION_CANDIDATE_GATED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        actor=actor,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        action=request.action.value,
        risk_score=risk.score,
        policy_decision="ALLOW" if policy.allowed else "DENY",
        result="SUCCEEDED",
        metadata={**event_details, "policy_reason": policy.reason},
    )
    await append_stream_event(
        session,
        event_type="incident.ai_action_evaluated",
        incident_id=incident.id,
        payload=event_details,
    )
    await session.flush()
    return AIActionGateResult(diagnosis=diagnosis, proposal=proposal, decision=decision)


async def _existing_gate_result(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    diagnosis_id: uuid.UUID,
    action: ActionType,
) -> tuple[ActionProposal, PolicyDecision] | None:
    proposals = list(
        (
            await session.execute(
                select(ActionProposal)
                .where(
                    ActionProposal.incident_id == incident_id,
                    ActionProposal.action_type == action,
                    ActionProposal.proposed_by == "cloudward-ai-advisory",
                )
                .order_by(ActionProposal.created_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    for proposal in proposals:
        if proposal.parameters.get("diagnosis_id") != str(diagnosis_id):
            continue
        decision = (
            await session.execute(
                select(PolicyDecision)
                .where(PolicyDecision.proposal_id == proposal.id)
                .order_by(PolicyDecision.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if decision is not None:
            return proposal, decision
    return None


def _bounded_labels(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    labels: dict[str, str] = {}
    for key, item in value.items():
        if len(labels) >= 30:
            break
        if not isinstance(key, str) or not isinstance(item, str) or not key:
            continue
        labels[key[:253]] = item[:253]
    return labels
