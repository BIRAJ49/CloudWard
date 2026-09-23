"""Safe integration readiness, delivery history, and worker callbacks."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import Notification, RecordStatus
from app.db.session import get_session
from app.errors import CloudWardError
from app.notifications.notifiers import NotificationMessage
from app.notifications.service import NotificationService
from app.rbac import Permission, require_permission

router = APIRouter(tags=["notifications"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
Admin = Annotated[Principal, Depends(require_permission(Permission.SETTINGS_MANAGE))]


class TeamsIntegrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    secret_managed_server_side: bool = True
    webhook_exposed: bool = False
    delivery_mode: str = "Microsoft Teams Workflows webhook"
    enabled_events: list[str]
    timeout_seconds: float
    maximum_attempts: int
    sent_count: int
    failed_count: int


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID | None
    channel: str
    status: RecordStatus
    event_type: str
    attempts: int
    max_attempts: int
    last_error: str | None
    delivered_at: datetime | None
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationDeliveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: uuid.UUID
    status: RecordStatus
    attempts: int


@router.get("/integrations/teams", response_model=TeamsIntegrationResponse)
async def teams_readiness(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TeamsIntegrationResponse:
    status_rows = (
        (
            await session.execute(
                select(Notification.status, func.count(Notification.id))
                .where(Notification.channel == "teams")
                .group_by(Notification.status)
            )
        )
        .tuples()
        .all()
    )
    counts: dict[RecordStatus, int] = dict(status_rows)
    return TeamsIntegrationResponse(
        configured=settings.teams_workflow_webhook_url is not None,
        enabled_events=sorted(settings.enabled_notification_events),
        timeout_seconds=settings.notification_timeout_seconds,
        maximum_attempts=settings.notification_max_attempts,
        sent_count=int(counts.get(RecordStatus.SUCCEEDED, 0)),
        failed_count=int(counts.get(RecordStatus.FAILED, 0)),
    )


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    channel: str | None = None,
    status: RecordStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Notification]:
    statement = select(Notification)
    if channel is not None:
        statement = statement.where(Notification.channel == channel)
    if status is not None:
        statement = statement.where(Notification.status == status)
    return list(
        (
            await session.execute(
                statement.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()
    )


@router.post("/integrations/teams/test", response_model=list[NotificationResponse], status_code=202)
async def test_teams(
    request: Request,
    principal: Admin,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[Notification]:
    if settings.teams_workflow_webhook_url is None:
        raise CloudWardError(
            "TEAMS_NOT_CONFIGURED",
            "Microsoft Teams workflow webhook is not configured",
            status_code=409,
        )
    message = NotificationMessage(
        event_type="integration_test",
        title="CloudWard Teams integration test",
        correlation_id=f"teams-test-{uuid.uuid4()}",
        severity="info",
        service="cloudward-control-plane",
        environment=settings.app_env,
        cause=f"Requested by {principal.login}",
        policy="No operational action",
        current_state="TEST",
        dashboard_url=str(settings.teams_dashboard_url) if settings.teams_dashboard_url else None,
    )
    records = await NotificationService(session, settings).queue(
        event_type="integration_test",
        message=message,
        channels=("dashboard", "teams"),
        publisher=request.app.state.task_publisher,
    )
    await session.commit()
    return records


@router.post(
    "/internal/notifications/{notification_id}/deliver",
    response_model=NotificationDeliveryResponse,
    include_in_schema=False,
)
async def deliver_notification_job(
    notification_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> NotificationDeliveryResponse:
    expected = f"Bearer {settings.worker_internal_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise CloudWardError(
            "WORKER_AUTHENTICATION_FAILED", "Worker authentication failed", status_code=401
        )
    try:
        notification = await NotificationService(session, settings).deliver(notification_id)
    except CloudWardError:
        # Preserve the retry count and failure audit without impacting the originating workflow.
        await session.commit()
        raise
    await session.commit()
    return NotificationDeliveryResponse(
        notification_id=notification.id,
        status=notification.status,
        attempts=notification.attempts,
    )
