"""Non-secret GitHub App integration posture endpoint."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import EvidenceSnapshot
from app.db.session import get_session
from app.events import append_stream_event
from app.github.factory import build_github_app_client
from app.github.schemas import (
    GitHubIntegrationStatus,
    GitHubIssueAutomationResponse,
    GitHubIssueContent,
    IncidentIssueRequest,
    SourceCorrelationEvidence,
    SourceCorrelationRequest,
)
from app.github.service import (
    GitHubIssueService,
    IncidentSourceCorrelationService,
    SourceCorrelationService,
)
from app.incidents.service import get_incident
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/integrations", tags=["integrations"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
IncidentOperator = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_CREATE))]


@router.get("/github", response_model=GitHubIntegrationStatus)
async def github_status(
    _: Viewer,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubIntegrationStatus:
    read_repositories = _csv(getattr(settings, "github_app_read_repositories", ""))
    issue_repositories = _csv(getattr(settings, "github_app_issue_repositories", ""))
    write_allowlist = _json_object(getattr(settings, "github_app_write_allowlist", "{}"))
    installation_id = getattr(settings, "github_app_installation_id", None)
    private_key = getattr(settings, "github_app_private_key", None)
    key_configured = bool(private_key and private_key.get_secret_value())
    return GitHubIntegrationStatus(
        configured=bool(settings.github_app_id and installation_id and key_configured),
        installation_id_configured=bool(installation_id),
        read_repository_count=len(read_repositories),
        issue_repository_count=len(issue_repositories),
        write_repository_count=len(write_allowlist),
    )


@router.post("/github/source/correlate", response_model=SourceCorrelationEvidence)
async def correlate_source(
    payload: SourceCorrelationRequest,
    _: Viewer,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SourceCorrelationEvidence:
    client = build_github_app_client(settings)
    return await SourceCorrelationService(client).correlate(payload)


@router.post(
    "/github/incidents/{incident_id}/source-correlation",
    response_model=SourceCorrelationEvidence,
)
async def correlate_incident_source(
    incident_id: uuid.UUID,
    payload: SourceCorrelationRequest,
    _: IncidentOperator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SourceCorrelationEvidence:
    """Persist a bounded Git comparison as evidence, never as proof of causation."""

    incident = await get_incident(session, incident_id)
    evidence = await IncidentSourceCorrelationService(
        session,
        build_github_app_client(settings),
    ).correlate_and_store(incident=incident, request=payload)
    await session.commit()
    return evidence


@router.post(
    "/github/incidents/{incident_id}/issue",
    response_model=GitHubIssueAutomationResponse,
)
async def create_incident_issue(
    incident_id: uuid.UUID,
    payload: IncidentIssueRequest,
    _: IncidentOperator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubIssueAutomationResponse:
    incident = await get_incident(session, incident_id)
    evidence = list(
        (
            await session.execute(
                select(EvidenceSnapshot.summary)
                .where(EvidenceSnapshot.incident_id == incident_id)
                .order_by(EvidenceSnapshot.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    dashboard_url = f"{str(settings.frontend_url).rstrip('/')}/incidents/{incident.id}"
    issue_body = "\n".join(
        [
            "Created by CloudWard",
            f"Incident: {incident.id}",
            f"Environment: {incident.environment.value}",
            f"Severity: {incident.severity}",
            f"State: {incident.state.value}",
            f"Risk: {incident.risk_score}/100"
            if incident.risk_score is not None
            else "Risk: unavailable",
            f"Summary: {(incident.summary or 'unavailable')[:2000]}",
            "Evidence summaries: "
            + ("; ".join(item[:800] for item in evidence) if evidence else "unavailable"),
            f"Recommended follow-up: {payload.recommended_follow_up}",
            f"CloudWard incident: {dashboard_url}",
        ]
    )
    content = GitHubIssueContent(
        title=f"[CloudWard] {incident.title}"[:200],
        body=issue_body[:10_000],
        labels=payload.labels,
    )
    result = await GitHubIssueService(session, build_github_app_client(settings)).create_once(
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        repository=payload.repository,
        content=content,
    )
    await append_stream_event(
        session,
        event_type="incident.github_issue",
        incident_id=incident.id,
        payload={
            "repository": result.issue.repository,
            "issue_number": result.issue.number,
            "issue_url": result.issue.url,
            "created": result.created,
        },
    )
    await session.commit()
    return GitHubIssueAutomationResponse(issue=result.issue, created=result.created)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
