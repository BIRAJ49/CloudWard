"""Application service for advisory diagnosis persistence and idempotent worker use."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.incident_context import build_incident_context
from app.ai.models import AIDiagnosisRecord
from app.ai.openrouter import OpenRouterProvider
from app.ai.persistence import DatabaseInvocationRecorder, store_diagnosis
from app.ai.safety import context_within_budget, evaluate_ai_admission
from app.ai.schemas import AIStatus, DiagnosisOutcome
from app.ai.service import DiagnosisRouter
from app.config import Settings
from app.db.models import Incident
from app.incidents.state_machine import IncidentState
from app.runbooks import RunbookLoader


async def diagnose_and_store(
    session: AsyncSession,
    *,
    incident: Incident,
    settings: Settings,
    runbooks: RunbookLoader,
    reuse_existing: bool = False,
) -> AIDiagnosisRecord:
    if reuse_existing:
        existing = (
            await session.execute(
                select(AIDiagnosisRecord)
                .where(AIDiagnosisRecord.incident_id == incident.id)
                .order_by(AIDiagnosisRecord.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    if not settings.ai_diagnosis_enabled:
        return await _persist_outcome(
            session,
            incident=incident,
            outcome=DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                failure_code="AI_DISABLED",
            ),
        )

    admission = await evaluate_ai_admission(
        session,
        incident_id=incident.id,
        settings=settings,
    )
    if not admission.allowed:
        return await _persist_outcome(
            session,
            incident=incident,
            outcome=DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                failure_code=admission.failure_code,
            ),
        )

    try:
        context = await build_incident_context(session, incident, runbooks)
    except (TypeError, ValueError):
        return await _persist_outcome(
            session,
            incident=incident,
            outcome=DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                failure_code="AI_CONTEXT_INVALID",
            ),
        )
    if not context_within_budget(context, settings):
        return await _persist_outcome(
            session,
            incident=incident,
            outcome=DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                failure_code="AI_EVIDENCE_BUDGET_EXCEEDED",
            ),
        )

    provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        timeout_seconds=settings.openrouter_timeout_seconds,
        max_retries=settings.openrouter_max_retries,
        max_context_tokens=settings.openrouter_max_context_tokens,
    )
    router = DiagnosisRouter(
        provider,
        primary_model=settings.cloudward_llm_primary_model,
        fallback_model=settings.cloudward_llm_fallback_model,
        escalation_model=settings.cloudward_llm_escalation_model,
        recorder=DatabaseInvocationRecorder(session),
    )
    outcome = await router.diagnose(
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        context=context,
        max_attempts=admission.remaining_calls,
    )
    return await _persist_outcome(
        session,
        incident=incident,
        outcome=outcome,
    )


async def latest_diagnosis(
    session: AsyncSession, incident_id: uuid.UUID
) -> AIDiagnosisRecord | None:
    return (
        await session.execute(
            select(AIDiagnosisRecord)
            .where(AIDiagnosisRecord.incident_id == incident_id)
            .order_by(AIDiagnosisRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _persist_outcome(
    session: AsyncSession,
    *,
    incident: Incident,
    outcome: DiagnosisOutcome,
) -> AIDiagnosisRecord:
    record = await store_diagnosis(
        session,
        incident_id=incident.id,
        correlation_id=incident.correlation_id,
        outcome=outcome,
    )
    if incident.state in {
        IncidentState.RESOLVED,
        IncidentState.BLOCKED,
        IncidentState.ESCALATED,
    }:
        from app.incident_memory.capture import capture_terminal_incident

        await capture_terminal_incident(session, incident)
    return record
