"""Authenticated webhook entrypoints; alerts are evidence, never commands."""

from __future__ import annotations

import hmac
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.alerts import AlertmanagerPayload, NormalizedAlert, ingest_alerts
from app.config import Settings, get_settings
from app.db.session import get_session
from app.errors import CloudWardError
from app.logging import correlation_id_context
from app.metrics import WEBHOOK_EVENTS_TOTAL
from app.security.rate_limit import alertmanager_rate_limit

MAX_ALERTMANAGER_BODY_BYTES = 1_048_576
ALERT_TASK = "cloudward.tasks.alerts.process"


class AlertWebhookItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_id: str
    incident_id: str | None
    duplicate: bool
    created_incident: bool
    status: str


class AlertWebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: int
    task_ids: list[str]
    results: list[AlertWebhookItem]


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/alertmanager", response_model=AlertWebhookResponse, status_code=202)
async def alertmanager_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    _rate_limit: Annotated[None, Depends(alertmanager_rate_limit)] = None,
) -> AlertWebhookResponse:
    expected = f"Bearer {settings.alertmanager_webhook_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        WEBHOOK_EVENTS_TOTAL.labels("alertmanager", "unauthenticated").inc()
        raise CloudWardError(
            "WEBHOOK_AUTHENTICATION_FAILED", "Alertmanager authentication failed", status_code=401
        )
    raw = await request.body()
    if len(raw) > MAX_ALERTMANAGER_BODY_BYTES:
        raise CloudWardError(
            "WEBHOOK_PAYLOAD_TOO_LARGE", "Alertmanager payload is too large", status_code=413
        )
    try:
        payload = AlertmanagerPayload.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise CloudWardError(
            "INVALID_ALERTMANAGER_PAYLOAD",
            "Alertmanager payload validation failed",
            status_code=422,
        ) from exc

    normalized = [NormalizedAlert.from_alertmanager(alert) for alert in payload.alerts]
    WEBHOOK_EVENTS_TOTAL.labels("alertmanager", "accepted").inc(len(normalized))
    correlation_id = correlation_id_context.get() or str(uuid.uuid4())
    ingested = await ingest_alerts(session, normalized, correlation_id=correlation_id)
    await session.commit()

    task_ids: list[str] = []
    for item, alert in zip(ingested, normalized, strict=True):
        if item.incident_id is None:
            continue
        result = await run_in_threadpool(
            request.app.state.task_publisher.send_task,
            ALERT_TASK,
            kwargs={
                "incident_id": item.incident_id,
                "alert": alert.model_dump(mode="json"),
                "correlation_id": correlation_id,
            },
            queue="incident-ingestion",
        )
        task_ids.append(str(result.id))
    return AlertWebhookResponse(
        accepted=len(normalized),
        task_ids=task_ids,
        results=[AlertWebhookItem.model_validate(item.__dict__) for item in ingested],
    )
