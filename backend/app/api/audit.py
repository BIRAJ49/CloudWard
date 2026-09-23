"""Bounded, RBAC-protected global audit feed for the operations dashboard."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AuditResponse
from app.auth.schemas import Principal
from app.db.models import AuditEvent
from app.db.session import get_session
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditResponse])
async def list_audit_events(
    _: Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars())
