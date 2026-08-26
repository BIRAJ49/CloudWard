"""Read-only access to bounded, persisted incident evidence."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import EvidenceResponse, VerificationResponse
from app.auth.schemas import Principal
from app.db.models import EvidencePhase, EvidenceSnapshot, VerificationRecord
from app.db.session import get_session
from app.evidence.types import EvidenceType
from app.incidents.service import get_incident
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/observability/incidents", tags=["observability"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_READ))]


@router.get("/{incident_id}/evidence", response_model=list[EvidenceResponse])
async def incident_evidence(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    evidence_type: EvidenceType | None = None,
    phase: EvidencePhase | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EvidenceSnapshot]:
    await get_incident(session, incident_id)
    query = select(EvidenceSnapshot).where(EvidenceSnapshot.incident_id == incident_id)
    if evidence_type is not None:
        query = query.where(EvidenceSnapshot.evidence_type == evidence_type)
    if phase is not None:
        query = query.where(EvidenceSnapshot.phase == phase)
    result = await session.execute(query.order_by(EvidenceSnapshot.created_at).limit(limit))
    return list(result.scalars())


@router.get("/{incident_id}/verifications", response_model=list[VerificationResponse])
async def incident_verifications(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VerificationRecord]:
    await get_incident(session, incident_id)
    result = await session.execute(
        select(VerificationRecord)
        .where(VerificationRecord.incident_id == incident_id)
        .order_by(VerificationRecord.attempt)
    )
    return list(result.scalars())
