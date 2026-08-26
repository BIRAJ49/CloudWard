from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.db.models import Cluster, Environment, Service
from app.db.session import get_session
from app.rbac import Permission, require_permission

router = APIRouter(tags=["inventory"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]


class ClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    environment: Environment
    context_name: str | None
    status: str
    labels: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    cluster_id: uuid.UUID
    name: str
    namespace: str
    deployment_name: str
    health_url: str | None
    criticality: str
    labels: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@router.get("/clusters", response_model=list[ClusterResponse])
async def clusters(
    _: Viewer, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[Cluster]:
    return list((await session.execute(select(Cluster).order_by(Cluster.name))).scalars())


@router.get("/services", response_model=list[ServiceResponse])
async def services(
    _: Viewer, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[Service]:
    return list((await session.execute(select(Service).order_by(Service.name))).scalars())
