from __future__ import annotations

from datetime import timedelta

import pytest

from app.ai.safety import evaluate_ai_admission
from app.config import Settings
from app.db.base import utc_now
from app.db.models import Environment, Incident, ModelInvocation


async def _incident(session, suffix: str) -> Incident:  # type: ignore[no-untyped-def]
    incident = Incident(
        correlation_id=f"ai-safety-{suffix}",
        incident_type="reliability",
        title="AI safety fixture",
        environment=Environment.STAGING,
        severity="warning",
    )
    session.add(incident)
    await session.flush()
    return incident


def _invocation(incident: Incident, *, status: str = "FAILED") -> ModelInvocation:
    return ModelInvocation(
        incident_id=incident.id,
        provider="openrouter",
        model="test/model",
        purpose="diagnose_incident",
        status=status,
        input_digest="0" * 64,
        usage={},
    )


@pytest.mark.asyncio
async def test_incident_call_budget_fails_closed(session, settings: Settings) -> None:
    incident = await _incident(session, "budget")
    session.add_all([_invocation(incident, status="SUCCEEDED") for _ in range(3)])
    await session.flush()

    admission = await evaluate_ai_admission(
        session,
        incident_id=incident.id,
        settings=settings.model_copy(update={"ai_max_model_calls_per_incident": 3}),
    )

    assert not admission.allowed
    assert admission.failure_code == "AI_CALL_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_consecutive_provider_failures_open_temporary_circuit(
    session, settings: Settings
) -> None:
    first = await _incident(session, "circuit-one")
    candidate = await _incident(session, "circuit-two")
    failures = [_invocation(first) for _ in range(3)]
    for index, invocation in enumerate(failures):
        invocation.created_at = utc_now() - timedelta(seconds=index)
    session.add_all(failures)
    await session.flush()

    admission = await evaluate_ai_admission(
        session,
        incident_id=candidate.id,
        settings=settings.model_copy(
            update={
                "ai_circuit_breaker_failure_threshold": 3,
                "ai_circuit_breaker_window_seconds": 300,
            }
        ),
    )

    assert not admission.allowed
    assert admission.failure_code == "AI_CIRCUIT_OPEN"
