"""Idempotent typed action execution and bounded rollback decisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db.base import utc_now
from app.db.models import (
    ActionExecution,
    ActionProposal,
    ActorType,
    Approval,
    ApprovalDecision,
    Incident,
    RecordStatus,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.kubernetes import KubernetesExecutor
from app.metrics import REMEDIATION_ACTIONS_TOTAL, REMEDIATION_FAILURES_TOTAL
from app.remediation.actions import ActionType, get_action_metadata, require_executable_action


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    execution: ActionExecution
    claimed: bool


def action_idempotency_key(
    *,
    incident_id: uuid.UUID,
    runbook_id: str,
    action: ActionType,
    target: dict[str, Any],
    attempt: int,
) -> str:
    canonical = json.dumps(target, sort_keys=True, separators=(",", ":"), default=str)
    material = f"{incident_id}:{runbook_id}:{action.value}:{attempt}:{canonical}"
    return hashlib.sha256(material.encode()).hexdigest()


async def claim_action_execution(
    session: AsyncSession,
    *,
    incident: Incident,
    proposal: ActionProposal,
    runbook_id: str,
    target: dict[str, Any],
    attempt: int,
) -> ExecutionClaim:
    if attempt < 1 or attempt > 3:
        raise CloudWardError(
            "REMEDIATION_ATTEMPT_LIMIT",
            "Automatic remediation is limited to three attempts per incident",
            status_code=409,
        )
    key = action_idempotency_key(
        incident_id=incident.id,
        runbook_id=runbook_id,
        action=proposal.action_type,
        target=target,
        attempt=attempt,
    )
    existing = (
        await session.execute(select(ActionExecution).where(ActionExecution.idempotency_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return ExecutionClaim(existing, False)
    approval = (
        await session.execute(
            select(Approval)
            .where(Approval.proposal_id == proposal.id)
            .order_by(Approval.proposal_version.desc())
            .with_for_update()
            .limit(1)
        )
    ).scalar_one_or_none()
    if approval is not None:
        if approval.decision != ApprovalDecision.APPROVED:
            raise CloudWardError(
                "ACTION_APPROVAL_REQUIRED",
                "The proposal does not have a current approved decision",
                status_code=409,
            )
        if approval.execution_claimed_at is not None:
            raise CloudWardError(
                "APPROVED_ACTION_ALREADY_CLAIMED",
                "The approved proposal was already claimed for execution",
                status_code=409,
            )
    execution = ActionExecution(
        incident_id=incident.id,
        proposal_id=proposal.id,
        correlation_id=incident.correlation_id,
        action_type=proposal.action_type,
        attempt=attempt,
        status=RecordStatus.RUNNING,
        result={},
        idempotency_key=key,
    )
    session.add(execution)
    incident.retry_count = attempt
    await session.flush()
    if approval is not None:
        approval.execution_claimed_at = utc_now()
        approval.execution_reference = str(execution.id)
    await record_audit(
        session,
        event_type="ACTION_EXECUTION_CLAIMED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        action=proposal.action_type.value,
        risk_score=proposal.risk_score,
        result="SUCCEEDED",
        metadata={"execution_id": str(execution.id), "attempt": attempt, "idempotency_key": key},
    )
    await append_stream_event(
        session,
        event_type="remediation.progress",
        incident_id=incident.id,
        payload={
            "execution_id": str(execution.id),
            "action": proposal.action_type.value,
            "attempt": attempt,
            "status": RecordStatus.RUNNING.value,
        },
    )
    return ExecutionClaim(execution, True)


async def finish_action_execution(
    session: AsyncSession,
    *,
    incident: Incident,
    execution: ActionExecution,
    succeeded: bool,
    result: dict[str, Any],
    error_code: str | None = None,
) -> ActionExecution:
    execution.status = RecordStatus.SUCCEEDED if succeeded else RecordStatus.FAILED
    execution.result = result
    execution.error_code = error_code
    execution.completed_at = utc_now()
    REMEDIATION_ACTIONS_TOTAL.labels(execution.action_type.value, execution.status.value).inc()
    if not succeeded:
        REMEDIATION_FAILURES_TOTAL.labels(execution.action_type.value).inc()
    await record_audit(
        session,
        event_type="ACTION_EXECUTED",
        correlation_id=incident.correlation_id,
        incident_id=incident.id,
        action=execution.action_type.value,
        result=execution.status.value,
        metadata={
            "execution_id": str(execution.id),
            "attempt": execution.attempt,
            "error_code": error_code,
            "result": result,
        },
    )
    await append_stream_event(
        session,
        event_type="remediation.progress",
        incident_id=incident.id,
        payload={
            "execution_id": str(execution.id),
            "action": execution.action_type.value,
            "attempt": execution.attempt,
            "status": execution.status.value,
            "error_code": error_code,
        },
    )
    await session.flush()
    return execution


class RollbackDisposition(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ESCALATE = "ESCALATE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class RollbackCoordinator:
    def __init__(self, *, automatic_max_risk: int) -> None:
        self.automatic_max_risk = automatic_max_risk

    def decide(
        self,
        *,
        action: ActionType,
        risk_score: int,
        rollback_enabled: bool,
        policy_allows_rollback: bool,
    ) -> RollbackDisposition:
        metadata = get_action_metadata(action)
        if not rollback_enabled or not metadata.reversible or not metadata.rollback_capable:
            return RollbackDisposition.NOT_AVAILABLE
        if not policy_allows_rollback:
            return RollbackDisposition.ESCALATE
        if metadata.persistent:
            return (
                RollbackDisposition.AWAITING_APPROVAL
                if risk_score < 70
                else RollbackDisposition.ESCALATE
            )
        if risk_score <= self.automatic_max_risk:
            return RollbackDisposition.AUTOMATIC
        if risk_score < 70:
            return RollbackDisposition.AWAITING_APPROVAL
        return RollbackDisposition.ESCALATE

    async def rollback_scale(
        self,
        session: AsyncSession,
        *,
        incident: Incident,
        failed_execution: ActionExecution,
        kubernetes: KubernetesExecutor,
        maximum_replicas: int,
    ) -> ActionExecution:
        require_executable_action(ActionType.SCALE_STAGING_DEPLOYMENT, incident.environment.value)
        result = failed_execution.result
        namespace = str(result.get("namespace", ""))
        deployment = str(result.get("deployment", ""))
        previous = int(result.get("previous_replicas", 0))
        requested = int(result.get("requested_replicas", 0))
        if previous < 1 or requested < 1:
            raise CloudWardError(
                "ROLLBACK_STATE_UNAVAILABLE",
                "Recorded scale execution is missing a valid previous state",
                status_code=409,
            )
        proposal = await session.get(ActionProposal, failed_execution.proposal_id)
        if proposal is None:
            raise CloudWardError(
                "ACTION_PROPOSAL_NOT_FOUND", "Rollback proposal was not found", status_code=404
            )
        if failed_execution.attempt >= 3:
            raise CloudWardError(
                "REMEDIATION_ATTEMPT_LIMIT",
                "No rollback attempt remains after the third automatic action",
                status_code=409,
            )
        attempt = failed_execution.attempt + 1
        rollback = ActionExecution(
            incident_id=incident.id,
            proposal_id=proposal.id,
            correlation_id=incident.correlation_id,
            action_type=ActionType.SCALE_STAGING_DEPLOYMENT,
            attempt=attempt,
            status=RecordStatus.RUNNING,
            result={},
            idempotency_key=hashlib.sha256(
                f"rollback:{failed_execution.id}:{previous}".encode()
            ).hexdigest(),
            rollback_of_execution_id=failed_execution.id,
        )
        session.add(rollback)
        await session.flush()
        scaled = await kubernetes.scale_staging_deployment(
            namespace,
            deployment,
            replicas=previous,
            maximum_replicas=maximum_replicas,
            expected_current_replicas=requested,
        )
        rollback.status = RecordStatus.SUCCEEDED
        rollback.result = scaled.to_dict()
        rollback.completed_at = utc_now()
        failed_execution.rolled_back_at = utc_now()
        await record_audit(
            session,
            event_type="ACTION_ROLLED_BACK",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor="cloudward-rollback",
            actor_type=ActorType.SYSTEM,
            action=rollback.action_type.value,
            result="SUCCEEDED",
            metadata={
                "execution_id": str(rollback.id),
                "rollback_of": str(failed_execution.id),
                "restored_replicas": previous,
            },
        )
        await append_stream_event(
            session,
            event_type="remediation.progress",
            incident_id=incident.id,
            payload={
                "execution_id": str(rollback.id),
                "rollback_of": str(failed_execution.id),
                "action": rollback.action_type.value,
                "status": rollback.status.value,
            },
        )
        await session.flush()
        return rollback
