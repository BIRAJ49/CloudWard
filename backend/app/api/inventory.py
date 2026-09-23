from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.cluster_agent.models import ClusterAgentState
from app.cluster_agent.service import connection_status
from app.config import Settings
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
    agent_observed_at: datetime | None = None
    agent_received_at: datetime | None = None


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
    request: Request, _: Viewer, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ClusterResponse]:
    settings: Settings = request.app.state.settings
    rows = (
        await session.execute(
            select(Cluster, ClusterAgentState)
            .outerjoin(ClusterAgentState, ClusterAgentState.cluster_id == Cluster.id)
            .order_by(Cluster.name)
        )
    ).all()
    responses = []
    for cluster, state in rows:
        response = ClusterResponse.model_validate(cluster)
        if state is not None:
            response = response.model_copy(
                update={
                    "status": connection_status(
                        state, max_age=settings.cluster_agent_freshness_seconds
                    ),
                    "agent_observed_at": state.observed_at,
                    "agent_received_at": state.received_at,
                }
            )
        responses.append(response)
    return responses


@router.get("/services", response_model=list[ServiceResponse])
async def services(
    _: Viewer, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[Service]:
    return list((await session.execute(select(Service).order_by(Service.name))).scalars())
