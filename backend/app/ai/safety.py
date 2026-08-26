"""Database-backed admission controls for bounded advisory model use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context import IncidentContext
from app.config import Settings
from app.db.base import utc_now
from app.db.models import Incident, ModelInvocation


@dataclass(frozen=True, slots=True)
class AIAdmission:
    allowed: bool
    remaining_calls: int
    failure_code: str | None = None


async def evaluate_ai_admission(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    settings: Settings,
) -> AIAdmission:
    """Serialize per-incident admission and open the circuit on consecutive failures."""

    await session.execute(
        select(Incident.id).where(Incident.id == incident_id).with_for_update()
    )
    used_calls = int(
        (
            await session.execute(
                select(func.count(ModelInvocation.id)).where(
                    ModelInvocation.incident_id == incident_id,
                    ModelInvocation.provider == "openrouter",
                )
            )
        ).scalar_one()
    )
    remaining = settings.ai_max_model_calls_per_incident - used_calls
    if remaining <= 0:
        return AIAdmission(False, 0, "AI_CALL_BUDGET_EXHAUSTED")

    cutoff = utc_now() - timedelta(seconds=settings.ai_circuit_breaker_window_seconds)
    recent_statuses = list(
        (
            await session.execute(
                select(ModelInvocation.status)
                .where(
                    ModelInvocation.provider == "openrouter",
                    ModelInvocation.created_at >= cutoff,
                )
                .order_by(ModelInvocation.created_at.desc())
                .limit(settings.ai_circuit_breaker_failure_threshold)
            )
        ).scalars()
    )
    if (
        len(recent_statuses) >= settings.ai_circuit_breaker_failure_threshold
        and all(status == "FAILED" for status in recent_statuses)
    ):
        return AIAdmission(False, 0, "AI_CIRCUIT_OPEN")
    return AIAdmission(True, min(remaining, 3))


def context_within_budget(context: IncidentContext, settings: Settings) -> bool:
    return len(context.model_dump_json()) <= settings.ai_max_evidence_chars
