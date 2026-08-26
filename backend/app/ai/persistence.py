"""Persist sanitized model invocation metadata and operator-facing diagnosis only."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIDiagnosisRecord
from app.ai.schemas import AIOperation, DiagnosisOutcome, ProviderResult
from app.audit import record_audit
from app.db.models import ActorType, IncidentEvent, ModelInvocation
from app.events import append_stream_event


class InvocationRecorder(Protocol):
    async def success(
        self,
        *,
        incident_id: uuid.UUID,
        result: ProviderResult,
        fallback: bool,
        escalation: bool,
        correlation_id: str,
    ) -> None: ...

    async def failure(
        self,
        *,
        incident_id: uuid.UUID,
        operation: AIOperation,
        requested_model: str,
        error_code: str,
        latency_ms: int,
        fallback: bool,
        escalation: bool,
        correlation_id: str,
    ) -> None: ...


class NullInvocationRecorder:
    async def success(self, **_: object) -> None:
        return None

    async def failure(self, **_: object) -> None:
        return None


class DatabaseInvocationRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def success(
        self,
        *,
        incident_id: uuid.UUID,
        result: ProviderResult,
        fallback: bool,
        escalation: bool,
        correlation_id: str,
    ) -> None:
        usage = result.usage.model_dump(exclude_none=True)
        usage.update(
            {
                "requested_model": result.requested_model,
                "actual_model": result.actual_model,
                "fallback_used": fallback,
                "escalation_used": escalation,
                "latency_ms": result.latency_ms,
            }
        )
        self._session.add(
            ModelInvocation(
                incident_id=incident_id,
                provider="openrouter",
                model=result.actual_model[:128],
                purpose=result.operation.value,
                status="SUCCEEDED",
                input_digest=result.input_digest,
                usage=usage,
            )
        )
        await record_audit(
            self._session,
            event_type="AI_INVOCATION_COMPLETED",
            correlation_id=correlation_id,
            incident_id=incident_id,
            result="SUCCEEDED",
            metadata=usage,
        )
        if fallback:
            await record_audit(
                self._session,
                event_type="AI_FALLBACK_USED",
                correlation_id=correlation_id,
                incident_id=incident_id,
                result="SUCCEEDED",
                metadata={
                    "requested_model": result.requested_model,
                    "actual_model": result.actual_model,
                },
            )
        if escalation:
            await record_audit(
                self._session,
                event_type="AI_ESCALATION_USED",
                correlation_id=correlation_id,
                incident_id=incident_id,
                result="SUCCEEDED",
                metadata={
                    "requested_model": result.requested_model,
                    "actual_model": result.actual_model,
                },
            )

    async def failure(
        self,
        *,
        incident_id: uuid.UUID,
        operation: AIOperation,
        requested_model: str,
        error_code: str,
        latency_ms: int,
        fallback: bool,
        escalation: bool,
        correlation_id: str,
    ) -> None:
        input_digest = "0" * 64
        metadata = {
            "requested_model": requested_model,
            "actual_model": None,
            "fallback_used": fallback,
            "escalation_used": escalation,
            "latency_ms": latency_ms,
            "error_code": error_code,
        }
        self._session.add(
            ModelInvocation(
                incident_id=incident_id,
                provider="openrouter",
                model=requested_model[:128],
                purpose=operation.value,
                status="FAILED",
                input_digest=input_digest,
                usage=metadata,
            )
        )
        await record_audit(
            self._session,
            event_type="AI_INVOCATION_FAILED",
            correlation_id=correlation_id,
            incident_id=incident_id,
            result="FAILED",
            metadata=metadata,
        )


async def store_diagnosis(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    correlation_id: str,
    outcome: DiagnosisOutcome,
) -> AIDiagnosisRecord:
    proposal = outcome.proposal
    record = AIDiagnosisRecord(
        incident_id=incident_id,
        status=outcome.status.value,
        suspected_root_cause=proposal.suspected_root_cause if proposal else None,
        root_cause_category=proposal.root_cause_category if proposal else None,
        confidence=proposal.confidence if proposal else None,
        evidence_refs=proposal.evidence_refs if proposal else [],
        related_change=proposal.related_change.model_dump()
        if proposal and proposal.related_change
        else None,
        suggested_runbook=proposal.suggested_runbook if proposal else None,
        action_candidates=[item.value for item in proposal.action_candidates] if proposal else [],
        explanation=proposal.explanation if proposal else None,
        model=outcome.model_used[:128] if outcome.model_used else None,
        fallback_used=outcome.fallback_used,
        escalation_used=outcome.escalation_used,
        failure_code=outcome.failure_code,
    )
    session.add(record)
    public_details = {
        "status": outcome.status.value,
        "model": outcome.model_used,
        "fallback_used": outcome.fallback_used,
        "escalation_used": outcome.escalation_used,
        "confidence": proposal.confidence if proposal else None,
        "suggested_runbook": proposal.suggested_runbook if proposal else None,
        "action_candidates": [item.value for item in proposal.action_candidates]
        if proposal
        else [],
        "failure_code": outcome.failure_code,
        "advisory_only": True,
    }
    session.add(
        IncidentEvent(
            incident_id=incident_id,
            correlation_id=correlation_id,
            event_type="AI_DIAGNOSIS",
            from_state=None,
            to_state=None,
            actor="cloudward-ai",
            actor_type=ActorType.SERVICE,
            details=public_details,
        )
    )
    await append_stream_event(
        session,
        event_type="incident.ai_diagnosis",
        incident_id=incident_id,
        payload=public_details,
    )
    await record_audit(
        session,
        event_type="AI_DIAGNOSIS_GENERATED" if proposal else "AI_DIAGNOSIS_UNAVAILABLE",
        correlation_id=correlation_id,
        incident_id=incident_id,
        result="SUCCEEDED" if proposal else "UNAVAILABLE",
        metadata={
            **public_details,
            "evidence_refs": proposal.evidence_refs if proposal else [],
        },
    )
    await session.flush()
    return record
