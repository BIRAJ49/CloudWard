"""Audit service with secret redaction at the persistence boundary."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActorType, AuditEvent
from app.logging import redact


async def record_audit(
    session: AsyncSession,
    *,
    event_type: str,
    correlation_id: str,
    result: str,
    actor: str = "cloudward",
    actor_type: ActorType = ActorType.SYSTEM,
    actor_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    action: str | None = None,
    risk_score: int | None = None,
    policy_decision: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        actor_type=actor_type,
        actor_id=actor_id,
        incident_id=incident_id,
        correlation_id=correlation_id,
        event_type=event_type,
        action=action,
        risk_score=risk_score,
        policy_decision=policy_decision,
        result=result,
        event_metadata=redact(metadata or {}),
    )
    session.add(event)
    await session.flush()
    return event
