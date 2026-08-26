"""Explicit CloudWard incident state machine."""

from __future__ import annotations

from enum import StrEnum

from app.errors import CloudWardError


class IncidentState(StrEnum):
    DETECTED = "DETECTED"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    CLASSIFYING = "CLASSIFYING"
    DIAGNOSING = "DIAGNOSING"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    POLICY_EVALUATION = "POLICY_EVALUATION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ROLLBACK = "ROLLBACK"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


ALLOWED_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    IncidentState.DETECTED: frozenset(
        {
            IncidentState.COLLECTING_EVIDENCE,
            IncidentState.BLOCKED,
            IncidentState.ESCALATED,
        }
    ),
    IncidentState.COLLECTING_EVIDENCE: frozenset(
        {IncidentState.CLASSIFYING, IncidentState.BLOCKED, IncidentState.ESCALATED}
    ),
    IncidentState.CLASSIFYING: frozenset(
        {
            IncidentState.DIAGNOSING,
            IncidentState.ACTION_PROPOSED,
            IncidentState.BLOCKED,
            IncidentState.ESCALATED,
        }
    ),
    IncidentState.DIAGNOSING: frozenset(
        {IncidentState.ACTION_PROPOSED, IncidentState.BLOCKED, IncidentState.ESCALATED}
    ),
    IncidentState.ACTION_PROPOSED: frozenset(
        {IncidentState.POLICY_EVALUATION, IncidentState.BLOCKED, IncidentState.ESCALATED}
    ),
    IncidentState.POLICY_EVALUATION: frozenset(
        {
            IncidentState.AWAITING_APPROVAL,
            IncidentState.EXECUTING,
            IncidentState.BLOCKED,
            IncidentState.ESCALATED,
        }
    ),
    IncidentState.AWAITING_APPROVAL: frozenset(
        {
            IncidentState.POLICY_EVALUATION,
            IncidentState.EXECUTING,
            IncidentState.BLOCKED,
            IncidentState.ESCALATED,
        }
    ),
    IncidentState.EXECUTING: frozenset(
        {IncidentState.VERIFYING, IncidentState.ROLLBACK, IncidentState.ESCALATED}
    ),
    IncidentState.VERIFYING: frozenset(
        {
            IncidentState.EXECUTING,
            IncidentState.ROLLBACK,
            IncidentState.RESOLVED,
            IncidentState.ESCALATED,
        }
    ),
    IncidentState.ROLLBACK: frozenset(
        {IncidentState.VERIFYING, IncidentState.RESOLVED, IncidentState.ESCALATED}
    ),
    IncidentState.RESOLVED: frozenset(),
    IncidentState.BLOCKED: frozenset(),
    IncidentState.ESCALATED: frozenset(),
}


def transition_incident(current: IncidentState, target: IncidentState) -> IncidentState:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise CloudWardError(
            "INVALID_INCIDENT_TRANSITION",
            f"Cannot transition from {current.value} to {target.value}",
            status_code=409,
            details={"from_state": current.value, "to_state": target.value},
        )
    return target
