"""Optional diagnosis adapter for deterministic remediation workflows."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context import IncidentContext
from app.ai.openrouter import OpenRouterProvider
from app.ai.persistence import DatabaseInvocationRecorder, store_diagnosis
from app.ai.schemas import AIStatus, DiagnosisOutcome
from app.ai.safety import context_within_budget, evaluate_ai_admission
from app.ai.service import DiagnosisRouter
from app.config import Settings


class SupplementalDiagnoser(Protocol):
    async def diagnose(
        self,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        context: IncidentContext,
    ) -> DiagnosisOutcome: ...


class StoredSupplementalDiagnoser:
    """Persist the advisory outcome; it deliberately exposes no execution method."""

    def __init__(
        self, session: AsyncSession, router: DiagnosisRouter, settings: Settings
    ) -> None:
        self._session = session
        self._router = router
        self._settings = settings

    async def diagnose(
        self,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        context: IncidentContext,
    ) -> DiagnosisOutcome:
        admission = await evaluate_ai_admission(
            self._session,
            incident_id=incident_id,
            settings=self._settings,
        )
        if not admission.allowed or not context_within_budget(context, self._settings):
            outcome = DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                failure_code=(
                    admission.failure_code
                    if not admission.allowed
                    else "AI_EVIDENCE_BUDGET_EXCEEDED"
                ),
            )
            await store_diagnosis(
                self._session,
                incident_id=incident_id,
                correlation_id=correlation_id,
                outcome=outcome,
            )
            return outcome
        outcome = await self._router.diagnose(
            incident_id=incident_id,
            correlation_id=correlation_id,
            context=context,
            max_attempts=admission.remaining_calls,
        )
        await store_diagnosis(
            self._session,
            incident_id=incident_id,
            correlation_id=correlation_id,
            outcome=outcome,
        )
        return outcome


def build_supplemental_diagnoser(
    settings: Settings,
    session: AsyncSession,
) -> SupplementalDiagnoser | None:
    if not settings.ai_diagnosis_enabled or settings.openrouter_api_key is None:
        return None
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
    return StoredSupplementalDiagnoser(session, router, settings)
