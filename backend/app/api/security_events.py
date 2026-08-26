"""Authenticated runtime-security ingestion, query, and containment APIs."""

from __future__ import annotations

import json
import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_kubernetes_executor, get_opa_client
from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import ContainmentStatus, Environment, SecurityCategory, SecurityEvent
from app.db.session import get_session
from app.errors import CloudWardError
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.rbac import Permission, require_permission
from app.security.quarantine import apply_quarantine, remove_quarantine
from app.security.schemas import (
    QuarantineResponse,
    SecurityJobRequest,
    SecurityEventResponse,
    SecurityWebhookResponse,
    TetragonSecurityEvent,
)
from app.security.normalization import event_fingerprint
from app.security.service import ingest_security_event, security_event_response
from app.security.webhook_auth import authenticate_tetragon_request, read_bounded_body

router = APIRouter(tags=["security"])

Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
SecurityAdmin = Annotated[
    Principal, Depends(require_permission(Permission.ACTION_APPROVE_HIGHER_RISK))
]


@router.post(
    "/webhooks/security/tetragon",
    response_model=SecurityWebhookResponse,
    status_code=202,
)
async def tetragon_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SecurityWebhookResponse:
    body = await read_bounded_body(request, settings.tetragon_webhook_max_body_bytes)
    await authenticate_tetragon_request(request, body, settings)
    try:
        raw = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudWardError(
            "INVALID_SECURITY_EVENT", "Security event body must be valid JSON", status_code=422
        ) from exc
    try:
        event = TetragonSecurityEvent.model_validate(raw)
    except ValidationError as exc:
        details = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors(include_input=False)
        ]
        raise CloudWardError(
            "INVALID_SECURITY_EVENT",
            "Security event failed schema validation",
            status_code=422,
            details={"errors": details},
        ) from exc
    fingerprint = event_fingerprint(
        event, window_seconds=settings.security_dedup_window_seconds
    )
    publisher = request.app.state.task_publisher
    task_id = f"security-{fingerprint}"
    try:
        publisher.send_task(
            "cloudward.tasks.security.process",
            kwargs={
                "payload": SecurityJobRequest(
                    fingerprint=fingerprint, event=event
                ).model_dump(mode="json")
            },
            task_id=task_id,
            queue="incident-ingestion",
        )
    except Exception as exc:
        raise CloudWardError(
            "SECURITY_EVENT_QUEUE_UNAVAILABLE",
            "Security event queue is unavailable",
            status_code=503,
        ) from exc
    return SecurityWebhookResponse(
        accepted=True,
        queued=True,
        fingerprint=fingerprint,
        task_id=task_id,
    )


@router.post(
    "/internal/security/events/process",
    response_model=SecurityWebhookResponse,
    include_in_schema=False,
)
async def process_security_event_job(
    payload: SecurityJobRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SecurityWebhookResponse:
    expected = f"Bearer {settings.worker_internal_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise CloudWardError(
            "WORKER_AUTHENTICATION_FAILED",
            "Worker authentication failed",
            status_code=401,
        )
    computed = event_fingerprint(
        payload.event, window_seconds=settings.security_dedup_window_seconds
    )
    if not hmac.compare_digest(computed, payload.fingerprint):
        raise CloudWardError(
            "SECURITY_JOB_FINGERPRINT_MISMATCH",
            "Security job fingerprint does not match its normalized event",
            status_code=422,
        )
    outcome = await ingest_security_event(
        session, payload.event, settings=settings, opa=opa
    )
    await session.commit()
    await session.refresh(outcome.event)
    return SecurityWebhookResponse(
        accepted=True,
        queued=False,
        duplicate=outcome.duplicate,
        fingerprint=payload.fingerprint,
        event=security_event_response(outcome.event),
    )


@router.get("/security/events", response_model=list[SecurityEventResponse])
async def list_security_events(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    event_type: SecurityCategory | None = None,
    severity: str | None = None,
    environment: Environment | None = None,
    namespace: str | None = None,
    containment_status: ContainmentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SecurityEventResponse]:
    statement = select(SecurityEvent)
    if event_type is not None:
        statement = statement.where(SecurityEvent.event_type == event_type)
    if severity is not None:
        statement = statement.where(SecurityEvent.severity == severity)
    if environment is not None:
        statement = statement.where(SecurityEvent.environment == environment)
    if namespace is not None:
        statement = statement.where(SecurityEvent.namespace == namespace)
    if containment_status is not None:
        statement = statement.where(SecurityEvent.containment_status == containment_status)
    events = list(
        (
            await session.execute(
                statement.order_by(SecurityEvent.occurred_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()
    )
    return [security_event_response(event) for event in events]


@router.post(
    "/security/events/{event_id}/containment/apply",
    response_model=QuarantineResponse,
)
async def apply_event_containment(
    event_id: uuid.UUID,
    principal: SecurityAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
) -> QuarantineResponse:
    return QuarantineResponse.model_validate(
        await apply_quarantine(
            session,
            event_id=event_id,
            actor=principal.login,
            settings=settings,
            opa=opa,
            kubernetes=kubernetes,
        )
    )


@router.post(
    "/security/events/{event_id}/containment/remove",
    response_model=QuarantineResponse,
)
async def remove_event_containment(
    event_id: uuid.UUID,
    principal: SecurityAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
) -> QuarantineResponse:
    return QuarantineResponse.model_validate(
        await remove_quarantine(
            session,
            event_id=event_id,
            actor=principal.login,
            settings=settings,
            opa=opa,
            kubernetes=kubernetes,
        )
    )
