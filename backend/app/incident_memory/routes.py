"""Factual similar-incident API backed by deterministic PostgreSQL matching."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.db.models import Service
from app.db.session import get_session
from app.incident_memory.fingerprint import FingerprintInput, select_stable_labels
from app.incident_memory.models import IncidentMemoryRecord
from app.incident_memory.schemas import SimilarIncidentResponse
from app.incident_memory.service import IncidentMemoryService
from app.incidents.service import get_incident
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/incidents", tags=["incident-memory"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_READ))]


@router.get("/{incident_id}/similar", response_model=list[SimilarIncidentResponse])
async def similar_incidents(
    incident_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[SimilarIncidentResponse]:
    incident = await get_incident(session, incident_id)
    current = (
        await session.execute(
            select(IncidentMemoryRecord).where(IncidentMemoryRecord.incident_id == incident_id)
        )
    ).scalar_one_or_none()
    service = None
    if incident.service_id:
        service = (
            await session.execute(select(Service).where(Service.id == incident.service_id))
        ).scalar_one_or_none()
    query = FingerprintInput(
        service=current.service_key
        if current
        else service.name
        if service
        else str(incident.service_id or "unassigned"),
        incident_type=current.incident_type if current else incident.incident_type,
        alert_name=current.alert_name if current else incident.title,
        namespace=current.namespace if current else service.namespace if service else None,
        root_cause_category=current.root_cause_category if current else None,
        labels=select_stable_labels(
            current.stable_labels if current else service.labels if service else {}
        ),
    )
    return await IncidentMemoryService(session).find_similar(
        query,
        exclude_incident_id=incident_id,
        limit=limit,
    )
