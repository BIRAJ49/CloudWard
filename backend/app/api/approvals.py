"""Transactional approval queue API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_kubernetes_executor, get_opa_client
from app.approvals import ApprovalService
from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import Approval, ApprovalDecision, Environment
from app.db.session import get_session
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/approvals", tags=["approvals"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
Approver = Annotated[
    Principal, Depends(require_permission(Permission.ACTION_APPROVE_STANDARD))
]
Rejector = Annotated[Principal, Depends(require_permission(Permission.ACTION_REJECT))]


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    proposal_id: uuid.UUID
    decision: ApprovalDecision
    action: str
    environment: Environment
    risk_score: int
    blast_radius: int
    reversible: bool
    requested_by: str
    runbook: str | None
    reason: str | None
    proposal_version: int
    target_reference: str
    expected_state: dict[str, object]
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_comment: str | None
    invalidated_reason: str | None
    execution_claimed_at: datetime | None
    execution_reference: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    decision: ApprovalDecision | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Approval]:
    statement = select(Approval)
    if decision is not None:
        statement = statement.where(Approval.decision == decision)
    return list(
        (
            await session.execute(
                statement.order_by(Approval.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        from app.errors import CloudWardError

        raise CloudWardError("APPROVAL_NOT_FOUND", "Approval was not found", status_code=404)
    return approval


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    principal: Approver,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> Approval:
    approval = await ApprovalService(session, settings, kubernetes, opa).decide(
        approval_id,
        decision=ApprovalDecision.APPROVED,
        principal=principal,
        comment=payload.comment,
    )
    await session.commit()
    await session.refresh(approval)
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    principal: Rejector,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> Approval:
    approval = await ApprovalService(session, settings, kubernetes, opa).decide(
        approval_id,
        decision=ApprovalDecision.REJECTED,
        principal=principal,
        comment=payload.comment,
    )
    await session.commit()
    await session.refresh(approval)
    return approval
