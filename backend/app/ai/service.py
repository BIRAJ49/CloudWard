"""Model routing, fallback, escalation, and post-provider safety validation."""

from __future__ import annotations

import time
import uuid

from app.ai.context import IncidentContext
from app.ai.persistence import InvocationRecorder, NullInvocationRecorder
from app.ai.provider import LLMProvider, LLMProviderError
from app.ai.schemas import (
    AIOperation,
    AIStatus,
    DiagnosisOutcome,
    DiagnosisProposal,
    InvocationAttempt,
    ProviderResult,
)


class DiagnosisRouter:
    """Return recommendations only; this type deliberately has no executor dependency."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        primary_model: str,
        fallback_model: str,
        escalation_model: str,
        recorder: InvocationRecorder | None = None,
        low_confidence_threshold: float = 0.55,
        escalation_complexity_threshold: int = 70,
    ) -> None:
        self._provider = provider
        self._primary_model = primary_model
        self._fallback_model = fallback_model
        self._escalation_model = escalation_model
        self._recorder = recorder or NullInvocationRecorder()
        self._low_confidence_threshold = min(max(low_confidence_threshold, 0.0), 1.0)
        self._escalation_complexity_threshold = min(max(escalation_complexity_threshold, 0), 100)

    async def diagnose(
        self,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        context: IncidentContext,
        allow_escalation: bool = True,
        max_attempts: int = 3,
    ) -> DiagnosisOutcome:
        attempts: list[InvocationAttempt] = []
        attempt_limit = min(max(max_attempts, 0), 3)
        if attempt_limit == 0:
            return DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                attempts=attempts,
                failure_code="AI_CALL_BUDGET_EXHAUSTED",
            )
        primary = await self._attempt(
            incident_id=incident_id,
            correlation_id=correlation_id,
            context=context,
            model=self._primary_model,
            fallback=False,
            escalation=False,
            attempts=attempts,
        )
        fallback_used = False
        selected = primary
        if (
            selected is None
            and len(attempts) < attempt_limit
            and self._fallback_model != self._primary_model
        ):
            fallback_used = True
            selected = await self._attempt(
                incident_id=incident_id,
                correlation_id=correlation_id,
                context=context,
                model=self._fallback_model,
                fallback=True,
                escalation=False,
                attempts=attempts,
            )
        if selected is None:
            failure_code = attempts[-1].error_code if attempts else "AI_UNAVAILABLE"
            return DiagnosisOutcome(
                status=AIStatus.AI_UNAVAILABLE,
                fallback_used=fallback_used,
                attempts=attempts,
                failure_code=failure_code,
            )

        proposal = _diagnosis_output(selected)
        escalation_used = False
        if (
            allow_escalation
            and len(attempts) < attempt_limit
            and proposal.confidence < self._low_confidence_threshold
            and context.complexity_score >= self._escalation_complexity_threshold
            and self._escalation_model not in {selected.requested_model, selected.actual_model}
        ):
            escalation_used = True
            escalated = await self._attempt(
                incident_id=incident_id,
                correlation_id=correlation_id,
                context=context,
                model=self._escalation_model,
                fallback=False,
                escalation=True,
                attempts=attempts,
            )
            if escalated is not None:
                escalated_proposal = _diagnosis_output(escalated)
                if escalated_proposal.confidence >= proposal.confidence:
                    selected = escalated
                    proposal = escalated_proposal

        return DiagnosisOutcome(
            status=AIStatus.AVAILABLE,
            proposal=proposal,
            model_used=selected.actual_model,
            fallback_used=fallback_used,
            escalation_used=escalation_used,
            attempts=attempts,
        )

    async def _attempt(
        self,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        context: IncidentContext,
        model: str,
        fallback: bool,
        escalation: bool,
        attempts: list[InvocationAttempt],
    ) -> ProviderResult | None:
        started = time.monotonic()
        try:
            result = await self._provider.diagnose_incident(context, model=model)
            proposal = _diagnosis_output(result)
            validate_proposal(proposal, context)
        except LLMProviderError as exc:
            latency_ms = max(0, round((time.monotonic() - started) * 1000))
            attempts.append(
                InvocationAttempt(
                    requested_model=model,
                    success=False,
                    fallback=fallback,
                    escalation=escalation,
                    latency_ms=latency_ms,
                    error_code=exc.code,
                )
            )
            await self._recorder.failure(
                incident_id=incident_id,
                operation=AIOperation.DIAGNOSE_INCIDENT,
                requested_model=model,
                error_code=exc.code,
                latency_ms=latency_ms,
                fallback=fallback,
                escalation=escalation,
                correlation_id=correlation_id,
            )
            return None
        except Exception as exc:
            latency_ms = max(0, round((time.monotonic() - started) * 1000))
            error = LLMProviderError("AI_PROVIDER_FAILURE", "Unexpected AI provider failure")
            attempts.append(
                InvocationAttempt(
                    requested_model=model,
                    success=False,
                    fallback=fallback,
                    escalation=escalation,
                    latency_ms=latency_ms,
                    error_code=error.code,
                )
            )
            await self._recorder.failure(
                incident_id=incident_id,
                operation=AIOperation.DIAGNOSE_INCIDENT,
                requested_model=model,
                error_code=error.code,
                latency_ms=latency_ms,
                fallback=fallback,
                escalation=escalation,
                correlation_id=correlation_id,
            )
            del exc
            return None

        attempts.append(
            InvocationAttempt(
                requested_model=model,
                actual_model=result.actual_model,
                success=True,
                fallback=fallback,
                escalation=escalation,
                latency_ms=result.latency_ms,
            )
        )
        await self._recorder.success(
            incident_id=incident_id,
            result=result,
            fallback=fallback,
            escalation=escalation,
            correlation_id=correlation_id,
        )
        return result


def _diagnosis_output(result: ProviderResult) -> DiagnosisProposal:
    if not isinstance(result.output, DiagnosisProposal):
        raise LLMProviderError("AI_OUTPUT_INVALID", "Provider returned the wrong output schema")
    return result.output


def validate_proposal(proposal: DiagnosisProposal, context: IncidentContext) -> None:
    unknown_refs = set(proposal.evidence_refs) - set(context.evidence_refs)
    if unknown_refs:
        raise LLMProviderError(
            "AI_EVIDENCE_REFERENCE_INVALID", "Diagnosis references evidence not in the context"
        )
    if proposal.suggested_runbook and proposal.suggested_runbook not in context.runbook_ids:
        raise LLMProviderError("AI_RUNBOOK_INVALID", "Diagnosis references an unavailable runbook")
    if proposal.related_change:
        matching = [
            item
            for item in context.untrusted_evidence.git_changes
            if item.repository == proposal.related_change.repository
            and item.commit_sha.lower() == proposal.related_change.commit_sha.lower()
        ]
        known_files = {item.file for item in matching}
        if not matching or not set(proposal.related_change.files).issubset(known_files):
            raise LLMProviderError(
                "AI_CHANGE_REFERENCE_INVALID",
                "Diagnosis references a Git change not in the context",
            )


def uncertainty_risk_factor(confidence: float) -> int:
    """Advisory deterministic factor; lower confidence can only add risk."""

    bounded = min(max(confidence, 0.0), 1.0)
    return round((1.0 - bounded) * 20)
