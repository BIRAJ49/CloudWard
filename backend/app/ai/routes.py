"""Versioned diagnosis API; recommendations remain separate from action execution."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.action_boundary import evaluate_ai_action_candidate
from app.ai.application import diagnose_and_store, latest_diagnosis
from app.ai.models import AIDiagnosisRecord
from app.ai.schemas import (
    AIActionEvaluationRequest,
    AIActionEvaluationResponse,
    StoredDiagnosisResponse,
)
from app.api.dependencies import get_opa_client, get_runbook_loader
from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import Incident
from app.db.session import get_session
from app.errors import CloudWardError
from app.incidents.service import get_incident
from app.policies import OPAClient
from app.rbac import Permission, require_permission
from app.runbooks import RunbookLoader

router = APIRouter(prefix="/incidents", tags=["ai-diagnosis"])
internal_router = APIRouter(prefix="/internal/ai", tags=["internal"], include_in_schema=False)
Viewer = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_READ))]
Operator = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_CREATE))]


@router.get("/{incident_id}/diagnosis", response_model=StoredDiagnosisResponse)
async def get_diagnosis(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoredDiagnosisResponse:
    await get_incident(session, incident_id)
    record = await latest_diagnosis(session, incident_id)
    return _stored_response(record)


@router.post("/{incident_id}/diagnosis", response_model=StoredDiagnosisResponse)
async def request_diagnosis(
    incident_id: uuid.UUID,
    _: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    runbooks: Annotated[RunbookLoader, Depends(get_runbook_loader)],
) -> StoredDiagnosisResponse:
    incident = await get_incident(session, incident_id)
    record = await diagnose_and_store(
        session,
        incident=incident,
        settings=settings,
        runbooks=runbooks,
    )
    await session.commit()
    await session.refresh(record)
    return _stored_response(record)


@router.post(
    "/{incident_id}/diagnosis/actions/evaluate",
    response_model=AIActionEvaluationResponse,
)
async def evaluate_diagnosis_action(
    incident_id: uuid.UUID,
    payload: AIActionEvaluationRequest,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> AIActionEvaluationResponse:
    """Gate an AI suggestion through registry, risk, and OPA without execution."""

    incident = await get_incident(session, incident_id)
    result = await evaluate_ai_action_candidate(
        session,
        incident=incident,
        request=payload,
        opa=opa,
        actor=principal.login,
        actor_id=principal.user_id,
        policy_path=settings.opa_decision_path,
    )
    await session.commit()
    return AIActionEvaluationResponse(
        diagnosis_id=result.diagnosis.id,
        proposal_id=result.proposal.id,
        action=result.proposal.action_type,
        risk_score=result.proposal.risk_score,
        risk_classification=str(
            result.proposal.risk_calculation.get("classification", "UNKNOWN")
        ),
        policy_allowed=result.decision.allowed,
        requires_approval=result.decision.requires_approval,
        policy_reason=result.decision.reason,
        proposal_status=result.proposal.status.value,
    )


@internal_router.post(
    "/incidents/{incident_id}/diagnose",
    response_model=StoredDiagnosisResponse,
)
async def diagnose_incident_job(
    incident_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    runbooks: Annotated[RunbookLoader, Depends(get_runbook_loader)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> StoredDiagnosisResponse:
    expected = f"Bearer {settings.worker_internal_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise CloudWardError(
            "WORKER_AUTHENTICATION_FAILED",
            "Worker authentication failed",
            status_code=401,
        )
    incident = await get_incident(session, incident_id)
    record = await diagnose_and_store(
        session,
        incident=incident,
        settings=settings,
        runbooks=runbooks,
        reuse_existing=True,
    )
    await session.commit()
    await session.refresh(record)
    return _stored_response(record)


def _stored_response(record: AIDiagnosisRecord | None) -> StoredDiagnosisResponse:
    if record is None:
        return StoredDiagnosisResponse(status="NOT_REQUESTED")
    return StoredDiagnosisResponse(
        status=record.status,
        suspected_root_cause=record.suspected_root_cause,
        root_cause_category=record.root_cause_category,
        confidence=record.confidence,
        evidence_refs=record.evidence_refs,
        related_change=record.related_change,
        suggested_runbook=record.suggested_runbook,
        action_candidates=record.action_candidates,
        explanation=record.explanation,
        model_used=record.model,
        fallback_used=record.fallback_used,
        escalation_used=record.escalation_used,
        created_at=record.created_at.isoformat(),
    )
