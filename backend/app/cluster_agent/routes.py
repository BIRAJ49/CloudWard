"""Dedicated machine identity for intake; ordinary RBAC for read-only status."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.cluster_agent.models import ClusterAgentState
from app.cluster_agent.schemas import AgentReceipt, AgentReport
from app.cluster_agent.service import connection_status, ingest_report
from app.config import Settings
from app.db.models import Cluster
from app.db.session import get_session
from app.errors import CloudWardError
from app.rbac import Permission, require_permission
from app.security.webhook_auth import read_bounded_body

router = APIRouter(prefix="/agent", tags=["cluster-agent"])


@router.post("/reports", response_model=AgentReceipt, status_code=202)
async def agent_report(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> AgentReceipt:
    settings: Settings = request.app.state.settings
    if not settings.cluster_agent_enabled:
        raise CloudWardError("AGENT_DISABLED", "Cluster agent intake is disabled", status_code=503)
    expected = f"Bearer {settings.cluster_agent_token.get_secret_value()}"
    if not hmac.compare_digest(request.headers.get("authorization", ""), expected):
        raise CloudWardError(
            "AGENT_AUTHENTICATION_FAILED", "Agent authentication failed", status_code=401
        )
    raw = await read_bounded_body(request, 524_288, error_code="AGENT_REPORT_TOO_LARGE")
    try:
        report = AgentReport.model_validate_json(raw)
    except ValidationError as exc:
        # Validation errors may contain untrusted secret-bearing input: do not echo it.
        raise CloudWardError(
            "AGENT_REPORT_INVALID", "Agent report did not match the bounded schema", status_code=422
        ) from exc
    receipt = await ingest_report(session, report, settings)
    await session.commit()
    return receipt


@router.get("/clusters/{cluster_id}")
async def agent_status(
    cluster_id: uuid.UUID,
    request: Request,
    _: Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    if await session.get(Cluster, cluster_id) is None:
        raise CloudWardError("CLUSTER_NOT_FOUND", "Cluster was not found", status_code=404)
    state = await session.get(ClusterAgentState, cluster_id)
    if state is None:
        return {"cluster_id": str(cluster_id), "status": "NOT_REPORTED", "observation": None}
    settings: Settings = request.app.state.settings
    return {
        "cluster_id": str(cluster_id),
        "status": connection_status(state, max_age=settings.cluster_agent_freshness_seconds),
        "received_at": state.received_at,
        "observed_at": state.observed_at,
        "observation": state.payload,
        "authority": "evidence_only",
    }
