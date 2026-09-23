"""Transactional notification outbox and retriable delivery state."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.base import utc_now
from app.db.models import Incident, Notification, RecordStatus
from app.errors import CloudWardError
from app.logging import redact
from app.notifications.notifiers import (
    DashboardNotifier,
    GitHubIssueNotifier,
    NotificationMessage,
    Notifier,
    TeamsNotifier,
)

NOTIFICATION_TASK = "cloudward.tasks.notifications.deliver"


class NotificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def queue(
        self,
        *,
        event_type: str,
        message: NotificationMessage,
        channels: tuple[str, ...],
        publisher: Celery | None = None,
    ) -> list[Notification]:
        queued: list[Notification] = []
        for channel in channels:
            dedupe_source = f"{event_type}:{message.incident_id}:{message.current_state}:{channel}"
            dedupe_key = hashlib.sha256(dedupe_source.encode()).hexdigest()
            existing = (
                await self.session.execute(
                    select(Notification).where(
                        Notification.channel == channel,
                        Notification.dedupe_key == dedupe_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                queued.append(existing)
                continue
            notification = Notification(
                incident_id=message.incident_id,
                channel=channel,
                status=RecordStatus.PENDING,
                destination_reference=_destination_reference(channel, self.settings),
                event_type=event_type,
                dedupe_key=dedupe_key,
                attempts=0,
                max_attempts=self.settings.notification_max_attempts,
                payload=redact(message.model_dump(mode="json")),
            )
            self.session.add(notification)
            await self.session.flush()
            queued.append(notification)
            await record_audit(
                self.session,
                event_type="NOTIFICATION_QUEUED",
                correlation_id=message.correlation_id,
                incident_id=message.incident_id,
                action=channel,
                result="PENDING",
                metadata={
                    "notification_id": str(notification.id),
                    "notification_event": event_type,
                    "dedupe_key": dedupe_key,
                },
            )
            if publisher is not None:
                try:
                    publisher.send_task(
                        NOTIFICATION_TASK,
                        kwargs={"notification_id": str(notification.id)},
                        task_id=f"notification-{notification.id}",
                        queue="notifications",
                        countdown=2,
                    )
                except Exception:
                    # The durable PENDING record remains available for redelivery.
                    await record_audit(
                        self.session,
                        event_type="NOTIFICATION_DISPATCH_DEFERRED",
                        correlation_id=message.correlation_id,
                        incident_id=message.incident_id,
                        action=channel,
                        result="FAILED",
                        metadata={"notification_id": str(notification.id)},
                    )
        return queued

    async def deliver(self, notification_id: uuid.UUID) -> Notification:
        notification = (
            await self.session.execute(
                select(Notification).where(Notification.id == notification_id).with_for_update()
            )
        ).scalar_one_or_none()
        if notification is None:
            raise CloudWardError(
                "NOTIFICATION_NOT_FOUND", "Notification was not found", status_code=404
            )
        if notification.status == RecordStatus.SUCCEEDED:
            return notification
        if notification.attempts >= notification.max_attempts:
            raise CloudWardError(
                "NOTIFICATION_RETRIES_EXHAUSTED",
                "Notification exhausted its bounded retries",
                status_code=409,
            )
        notification.status = RecordStatus.RUNNING
        notification.attempts += 1
        message = NotificationMessage.model_validate(notification.payload)
        notifier = self._notifier(notification.channel)
        try:
            delivery = await notifier.deliver(self.session, message)
        except CloudWardError as exc:
            notification.status = (
                RecordStatus.FAILED
                if notification.attempts >= notification.max_attempts
                else RecordStatus.PENDING
            )
            notification.last_error = exc.code
            notification.next_attempt_at = utc_now() + timedelta(
                seconds=min(2**notification.attempts, 300)
            )
            await record_audit(
                self.session,
                event_type=(
                    "TEAMS_NOTIFICATION_FAILED"
                    if notification.channel == "teams"
                    else "NOTIFICATION_FAILED"
                ),
                correlation_id=message.correlation_id,
                incident_id=message.incident_id,
                action=notification.channel,
                result="FAILED",
                metadata={
                    "notification_id": str(notification.id),
                    "attempt": notification.attempts,
                    "max_attempts": notification.max_attempts,
                    "error_code": exc.code,
                    "remediation_rolled_back": False,
                },
            )
            raise
        notification.status = RecordStatus.SUCCEEDED
        notification.destination_reference = delivery.destination_reference
        notification.last_error = None
        notification.next_attempt_at = None
        notification.delivered_at = utc_now()
        await record_audit(
            self.session,
            event_type=(
                "TEAMS_NOTIFICATION_SENT"
                if notification.channel == "teams"
                else "NOTIFICATION_SENT"
            ),
            correlation_id=message.correlation_id,
            incident_id=message.incident_id,
            action=notification.channel,
            result="SUCCEEDED",
            metadata={
                "notification_id": str(notification.id),
                "attempt": notification.attempts,
                "destination_reference": delivery.destination_reference,
                "external_reference": delivery.external_reference,
            },
        )
        return notification

    def _notifier(self, channel: str) -> Notifier:
        if channel == "dashboard":
            return DashboardNotifier()
        if channel == "teams":
            return TeamsNotifier(self.settings)
        if channel == "github_issue":
            return GitHubIssueNotifier(self.settings)
        raise CloudWardError(
            "NOTIFIER_UNKNOWN", "Notification channel is not registered", status_code=422
        )


async def queue_incident_notification(
    session: AsyncSession,
    settings: Settings,
    *,
    event_type: str,
    incident: Incident,
    details: dict[str, Any] | None = None,
    publisher: Celery | None = None,
) -> list[Notification]:
    if event_type not in settings.enabled_notification_events:
        return []
    detail = details or {}
    dashboard_url = None
    if settings.teams_dashboard_url is not None:
        dashboard_url = f"{str(settings.teams_dashboard_url).rstrip('/')}/incidents/{incident.id}"
    message = NotificationMessage(
        event_type=event_type,
        title=incident.title,
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        severity=incident.severity,
        service=str(detail.get("service") or incident.title),
        environment=incident.environment.value,
        cause=str(detail.get("cause") or incident.summary or "Not yet established"),
        risk_score=incident.risk_score,
        policy=str(detail.get("policy_reason") or detail.get("reason") or "See policy audit"),
        current_state=incident.state.value,
        dashboard_url=dashboard_url,
        details=redact(detail),
    )
    channels = ["dashboard"]
    if settings.teams_workflow_webhook_url is not None:
        channels.append("teams")
    if (
        event_type in {"incident_escalated", "remediation_failed"}
        and settings.github_app_issue_repositories
    ):
        channels.append("github_issue")
    return await NotificationService(session, settings).queue(
        event_type=event_type,
        message=message,
        channels=tuple(channels),
        publisher=publisher,
    )


def _destination_reference(channel: str, settings: Settings) -> str:
    if channel == "teams" and settings.teams_workflow_webhook_url is not None:
        value = settings.teams_workflow_webhook_url.get_secret_value()
        return f"configured:{hashlib.sha256(value.encode()).hexdigest()[:12]}"
    return "configured" if channel == "github_issue" else "authenticated-sse"
