"""Incident, timeline, action, approval, and deterministic demo APIs."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_kubernetes_executor, get_opa_client, get_runbook_loader
from app.approvals import ApprovalService, ensure_runtime_approval
from app.api.schemas import (
    ActionExecutionResponse,
    ActionProposalResponse,
    AlertResponse,
    ApprovalRequest,
    AuditResponse,
    EvidenceResponse,
    IncidentCreate,
    IncidentDetailResponse,
    IncidentEventResponse,
    IncidentResponse,
    IncidentTransitionRequest,
    PolicyDecisionResponse,
    VerificationResponse,
)
from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import (
    ActionExecution,
    ActionProposal,
    ActorType,
    Approval,
    ApprovalDecision,
    AlertRecord,
    AuditEvent,
    Environment,
    EvidenceSnapshot,
    Incident,
    IncidentEvent,
    PolicyDecision,
    VerificationRecord,
)
from app.db.session import get_session
from app.errors import CloudWardError
from app.incidents.service import change_incident_state, create_incident, get_incident
from app.incidents.state_machine import IncidentState
from app.kubernetes import KubernetesExecutor
from app.logging import correlation_id_context
from app.policies import OPAClient
from app.rbac import Permission, require_permission
from app.remediation.pipeline import PipelineOutcome, UnhealthyPodPipeline, UnhealthyPodTarget
from app.runbooks import RunbookLoader
from app.security.rate_limit import demo_rate_limit

router = APIRouter(prefix="/incidents", tags=["incidents"])

Viewer = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_READ))]
Operator = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_CREATE))]
Admin = Annotated[Principal, Depends(require_permission(Permission.SETTINGS_MANAGE))]


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    state: IncidentState | None = None,
    environment: Environment | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Incident]:
    statement = select(Incident)
    if state is not None:
        statement = statement.where(Incident.state == state)
    if environment is not None:
        statement = statement.where(Incident.environment == environment)
    result = await session.execute(
        statement.order_by(Incident.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars())


@router.post("", response_model=IncidentResponse, status_code=201)
async def post_incident(
    payload: IncidentCreate,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Incident:
    incident = await create_incident(
        session,
        correlation_id=correlation_id_context.get() or str(uuid.uuid4()),
        incident_type=payload.incident_type,
        title=payload.title,
        summary=payload.summary,
        environment=payload.environment,
        service_id=payload.service_id,
        cluster_id=payload.cluster_id,
        actor=principal.login,
        actor_type=ActorType.USER,
    )
    await session.commit()
    await session.refresh(incident)
    return incident


@router.post("/demo/unhealthy-pod", response_model=PipelineOutcome)
async def trigger_unhealthy_pod(
    payload: UnhealthyPodTarget,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    runbooks: Annotated[RunbookLoader, Depends(get_runbook_loader)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    _rate_limit: Annotated[None, Depends(demo_rate_limit)],
) -> PipelineOutcome:
    pipeline = UnhealthyPodPipeline(
        session=session,
        kubernetes=kubernetes,
        runbooks=runbooks,
        opa=opa,
        settings=settings,
    )
    return await pipeline.run(
        payload,
        correlation_id=correlation_id_context.get() or str(uuid.uuid4()),
        actor=principal.login,
        actor_type=ActorType.USER,
    )


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
async def incident_detail(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentDetailResponse:
    incident = await get_incident(session, incident_id)
    evidence = list(
        (
            await session.execute(
                select(EvidenceSnapshot)
                .where(EvidenceSnapshot.incident_id == incident_id)
                .order_by(EvidenceSnapshot.created_at)
            )
        ).scalars()
    )
    proposals = list(
        (
            await session.execute(
                select(ActionProposal)
                .where(ActionProposal.incident_id == incident_id)
                .order_by(ActionProposal.created_at)
            )
        ).scalars()
    )
    decisions = list(
        (
            await session.execute(
                select(PolicyDecision)
                .where(PolicyDecision.incident_id == incident_id)
                .order_by(PolicyDecision.created_at)
            )
        ).scalars()
    )
    executions = list(
        (
            await session.execute(
                select(ActionExecution)
                .where(ActionExecution.incident_id == incident_id)
                .order_by(ActionExecution.attempt)
            )
        ).scalars()
    )
    verifications = list(
        (
            await session.execute(
                select(VerificationRecord)
                .where(VerificationRecord.incident_id == incident_id)
                .order_by(VerificationRecord.attempt)
            )
        ).scalars()
    )
    alerts = list(
        (
            await session.execute(
                select(AlertRecord)
                .where(AlertRecord.incident_id == incident_id)
                .order_by(AlertRecord.created_at)
            )
        ).scalars()
    )
    audit = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.incident_id == incident_id)
                .order_by(AuditEvent.created_at)
            )
        ).scalars()
    )
    base = IncidentResponse.model_validate(incident)
    return IncidentDetailResponse(
        **base.model_dump(),
        events=[IncidentEventResponse.model_validate(event) for event in incident.events],
        evidence=[EvidenceResponse.model_validate(item) for item in evidence],
        actions=[ActionProposalResponse.model_validate(item) for item in proposals],
        executions=[ActionExecutionResponse.model_validate(item) for item in executions],
        verifications=[VerificationResponse.model_validate(item) for item in verifications],
        alerts=[AlertResponse.model_validate(item) for item in alerts],
        policy_decisions=[PolicyDecisionResponse.model_validate(item) for item in decisions],
        audit_events=[AuditResponse.model_validate(item) for item in audit],
    )


@router.get("/{incident_id}/events", response_model=list[IncidentEventResponse])
async def incident_events(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[IncidentEvent]:
    await get_incident(session, incident_id)
    result = await session.execute(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at)
    )
    return list(result.scalars())


@router.get("/{incident_id}/actions", response_model=list[ActionProposalResponse])
async def incident_actions(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ActionProposal]:
    await get_incident(session, incident_id)
    result = await session.execute(
        select(ActionProposal)
        .where(ActionProposal.incident_id == incident_id)
        .order_by(ActionProposal.created_at)
    )
    return list(result.scalars())


@router.get("/{incident_id}/audit", response_model=list[AuditResponse])
async def incident_audit(
    incident_id: uuid.UUID,
    _: Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AuditEvent]:
    await get_incident(session, incident_id)
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.incident_id == incident_id)
        .order_by(AuditEvent.created_at)
    )
    return list(result.scalars())


@router.post("/{incident_id}/transitions", response_model=IncidentResponse)
async def transition_endpoint(
    incident_id: uuid.UUID,
    payload: IncidentTransitionRequest,
    principal: Admin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Incident:
    incident = await get_incident(session, incident_id)
    await change_incident_state(
        session,
        incident,
        payload.state,
        actor=principal.login,
        actor_type=ActorType.USER,
        details={"reason": payload.reason} if payload.reason else {},
    )
    await session.commit()
    await session.refresh(incident)
    return incident


async def _decision(
    *,
    incident_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: ApprovalRequest,
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
    kubernetes: KubernetesExecutor,
    opa: OPAClient,
    decision: ApprovalDecision,
) -> dict[str, Any]:
    incident = await get_incident(session, incident_id)
    result = await session.execute(
        select(ActionProposal).where(
            ActionProposal.id == proposal_id, ActionProposal.incident_id == incident_id
        )
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise CloudWardError(
            "ACTION_PROPOSAL_NOT_FOUND", "Action proposal was not found", status_code=404
        )
    if incident.state != IncidentState.AWAITING_APPROVAL:
        raise CloudWardError(
            "INCIDENT_NOT_AWAITING_APPROVAL",
            "Incident is not awaiting approval",
            status_code=409,
        )
    approval = (
        await session.execute(
            select(Approval).where(
                Approval.proposal_id == proposal.id,
                Approval.proposal_version == 1,
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        approval = await ensure_runtime_approval(
            session,
            incident=incident,
            proposal=proposal,
            settings=settings,
            requested_by="cloudward",
            reason="Legacy incident approval route",
        )
    approval = await ApprovalService(session, settings, kubernetes, opa).decide(
        approval.id,
        decision=decision,
        principal=principal,
        comment=payload.reason,
    )
    await session.commit()
    return {
        "approval_id": approval.id,
        "decision": approval.decision.value,
        "incident_state": incident.state.value,
    }


@router.post("/{incident_id}/actions/{proposal_id}/approve")
async def approve_action(
    incident_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: ApprovalRequest,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.ACTION_APPROVE_STANDARD))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> dict[str, Any]:
    return await _decision(
        incident_id=incident_id,
        proposal_id=proposal_id,
        payload=payload,
        principal=principal,
        session=session,
        settings=settings,
        kubernetes=kubernetes,
        opa=opa,
        decision=ApprovalDecision.APPROVED,
    )


@router.post("/{incident_id}/actions/{proposal_id}/reject")
async def reject_action(
    incident_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: ApprovalRequest,
    principal: Annotated[Principal, Depends(require_permission(Permission.ACTION_REJECT))],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> dict[str, Any]:
    return await _decision(
        incident_id=incident_id,
        proposal_id=proposal_id,
        payload=payload,
        principal=principal,
        session=session,
        settings=settings,
        kubernetes=kubernetes,
        opa=opa,
        decision=ApprovalDecision.REJECTED,
    )
