"""Admin-only global role mapping management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.auth.schemas import Principal
from app.db.models import ActorType, RoleMapping, User
from app.db.session import get_session
from app.errors import CloudWardError
from app.logging import correlation_id_context
from app.rbac import Permission, Role, require_permission

router = APIRouter(prefix="/role-mappings", tags=["role mappings"])
Admin = Annotated[Principal, Depends(require_permission(Permission.ROLE_MANAGE))]


class RoleMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    scope: str
    granted_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


@router.get("", response_model=list[RoleMappingResponse])
async def list_role_mappings(
    _: Admin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RoleMapping]:
    return list(
        (
            await session.execute(
                select(RoleMapping)
                .where(RoleMapping.scope == "global")
                .order_by(RoleMapping.created_at)
            )
        ).scalars()
    )


@router.put("/{user_id}", response_model=RoleMappingResponse)
async def update_role_mapping(
    user_id: uuid.UUID,
    payload: RoleUpdate,
    principal: Admin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleMapping:
    user = await session.get(User, user_id)
    if user is None:
        raise CloudWardError("USER_NOT_FOUND", "User was not found", status_code=404)
    result = await session.execute(
        select(RoleMapping).where(RoleMapping.user_id == user_id, RoleMapping.scope == "global")
    )
    mapping = result.scalar_one_or_none()
    previous: str | None = None
    if mapping is None:
        mapping = RoleMapping(
            user_id=user_id,
            role=payload.role,
            scope="global",
            granted_by=principal.user_id if principal.persisted else None,
        )
        session.add(mapping)
    else:
        previous = mapping.role.value
        mapping.role = payload.role
        mapping.granted_by = principal.user_id if principal.persisted else None
    await record_audit(
        session,
        event_type="ROLE_MAPPING_UPDATED",
        correlation_id=correlation_id_context.get() or "role-management",
        actor=principal.login,
        actor_type=ActorType.USER,
        actor_id=principal.user_id if principal.persisted else None,
        result="SUCCEEDED",
        metadata={"user_id": str(user_id), "from_role": previous, "to_role": payload.role.value},
    )
    await session.commit()
    await session.refresh(mapping)
    return mapping
