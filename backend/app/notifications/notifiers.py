"""Notifier abstraction with dashboard, Teams, and GitHub Issue adapters."""

from __future__ import annotations

import uuid
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import CloudWardError
from app.events import append_stream_event
from app.github.factory import build_github_app_client
from app.github.schemas import GitHubIssueContent
from app.github.service import GitHubIssueService
from app.logging import redact

TEAMS_HOST_SUFFIXES = (
    ".logic.azure.com",
    ".webhook.office.com",
    ".powerplatform.com",
    ".powerautomate.com",
)


class NotificationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    incident_id: uuid.UUID | None = None
    correlation_id: str = Field(min_length=1, max_length=128)
    severity: str = Field(default="info", max_length=16)
    service: str = Field(default="unknown", max_length=255)
    environment: str = Field(default="unknown", max_length=32)
    cause: str = Field(default="Not yet established", max_length=1000)
    risk_score: int | None = Field(default=None, ge=0, le=100)
    policy: str = Field(default="See CloudWard policy record", max_length=1000)
    current_state: str = Field(default="UNKNOWN", max_length=64)
    dashboard_url: str | None = Field(default=None, max_length=2048)
    details: dict[str, object] = Field(default_factory=dict)


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: str
    destination_reference: str
    external_reference: str | None = None


class Notifier(Protocol):
    channel: str

    async def deliver(
        self, session: AsyncSession, message: NotificationMessage
    ) -> DeliveryResult: ...


class DashboardNotifier:
    channel = "dashboard"

    async def deliver(self, session: AsyncSession, message: NotificationMessage) -> DeliveryResult:
        await append_stream_event(
            session,
            event_type="notification.dashboard",
            incident_id=message.incident_id,
            payload=message.model_dump(mode="json"),
        )
        return DeliveryResult(channel=self.channel, destination_reference="authenticated-sse")


class TeamsNotifier:
    channel = "teams"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    async def deliver(self, session: AsyncSession, message: NotificationMessage) -> DeliveryResult:
        del session
        if self.settings.teams_workflow_webhook_url is None:
            raise CloudWardError(
                "TEAMS_NOT_CONFIGURED",
                "Microsoft Teams workflow webhook is not configured",
                status_code=503,
            )
        url = self.settings.teams_workflow_webhook_url.get_secret_value()
        host = (urlsplit(url).hostname or "").lower()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or not any(host.endswith(suffix) for suffix in TEAMS_HOST_SUFFIXES)
        ):
            raise CloudWardError(
                "TEAMS_WEBHOOK_DENIED",
                "Microsoft Teams webhook is outside the configured HTTPS host boundary",
                status_code=503,
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.notification_timeout_seconds,
            follow_redirects=False,
        )
        try:
            response = await client.post(url, json=_adaptive_card(message))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CloudWardError(
                "TEAMS_DELIVERY_FAILED",
                "Microsoft Teams rejected the notification",
                status_code=502,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        return DeliveryResult(
            channel=self.channel,
            destination_reference=f"teams-workflow:{host}",
        )


class GitHubIssueNotifier:
    channel = "github_issue"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def deliver(self, session: AsyncSession, message: NotificationMessage) -> DeliveryResult:
        if message.incident_id is None:
            raise CloudWardError(
                "GITHUB_ISSUE_INCIDENT_REQUIRED",
                "GitHub Issue notifications require an incident",
                status_code=409,
            )
        repositories = [
            value.strip()
            for value in self.settings.github_app_issue_repositories.split(",")
            if value.strip()
        ]
        if not repositories:
            raise CloudWardError(
                "GITHUB_ISSUE_NOT_CONFIGURED",
                "No allowlisted GitHub Issue repository is configured",
                status_code=503,
            )
        client = build_github_app_client(self.settings)
        content = GitHubIssueContent(
            title=f"CloudWard: {message.title}"[:200],
            body=_github_issue_body(message),
            labels=["cloudward", "incident", message.severity.lower()[:50]],
        )
        result = await GitHubIssueService(session, client).create_once(
            incident_id=message.incident_id,
            correlation_id=message.correlation_id,
            repository=repositories[0],
            content=content,
        )
        return DeliveryResult(
            channel=self.channel,
            destination_reference=result.issue.repository,
            external_reference=result.issue.url,
        )


def _adaptive_card(message: NotificationMessage) -> dict[str, object]:
    facts = [
        {"title": "Severity", "value": message.severity},
        {"title": "Service", "value": message.service},
        {"title": "Environment", "value": message.environment},
        {"title": "Incident", "value": str(message.incident_id or "n/a")},
        {"title": "Cause", "value": message.cause},
        {
            "title": "Risk",
            "value": f"{message.risk_score}/100" if message.risk_score is not None else "n/a",
        },
        {"title": "Policy", "value": message.policy},
        {"title": "Current state", "value": message.current_state},
    ]
    body: list[dict[str, object]] = [
        {"type": "TextBlock", "text": "CloudWard Incident", "weight": "Bolder", "size": "Medium"},
        {"type": "TextBlock", "text": message.title, "wrap": True},
        {"type": "FactSet", "facts": facts},
    ]
    if message.dashboard_url:
        body.append(
            {
                "type": "ActionSet",
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "Open CloudWard",
                        "url": message.dashboard_url,
                    }
                ],
            }
        )
    payload = redact(
        {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                    },
                }
            ],
        }
    )
    return payload if isinstance(payload, dict) else {}


def _github_issue_body(message: NotificationMessage) -> str:
    dashboard = f"\n- Dashboard: {message.dashboard_url}" if message.dashboard_url else ""
    return (
        "Created by CloudWard\n\n"
        f"- Event: {message.event_type}\n"
        f"- Incident: {message.incident_id}\n"
        f"- Severity: {message.severity}\n"
        f"- Service: {message.service}\n"
        f"- Environment: {message.environment}\n"
        f"- Current state: {message.current_state}\n"
        f"- Risk: {message.risk_score if message.risk_score is not None else 'n/a'}\n"
        f"- Cause: {message.cause}\n"
        f"- Policy: {message.policy}{dashboard}\n\n"
        "Review the complete evidence and audit trail in CloudWard before taking action."
    )
