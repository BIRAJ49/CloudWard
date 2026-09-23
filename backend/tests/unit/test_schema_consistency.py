"""Keep create_all-based tests aligned with safety rules in migrated PostgreSQL."""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, insert
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ActionExecution,
    Approval,
    FinOpsRecommendation,
    Notification,
    RecordStatus,
    SecurityEvent,
)
from app.github.models import GitHubAutomationRecord


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            Approval,
            {
                "ck_approvals_approval_risk_score_range",
                "ck_approvals_approval_proposal_version_positive",
            },
        ),
        (
            FinOpsRecommendation,
            {
                "ck_finops_recommendations_finops_risk_score_range",
                "ck_finops_recommendations_finops_confidence_range",
            },
        ),
        (
            Notification,
            {
                "ck_notifications_notification_attempts_nonnegative",
                "ck_notifications_notification_max_attempts_positive",
            },
        ),
    ],
)
def test_safety_checks_exist_in_test_schema(model, expected):
    checks = {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert expected <= checks


@pytest.mark.parametrize(("attempts", "max_attempts"), [(-1, 5), (0, 0)])
async def test_invalid_notification_retry_bounds_rejected(session, attempts, max_attempts):
    with pytest.raises(IntegrityError):
        await session.execute(
            insert(Notification).values(
                channel="test",
                status=RecordStatus.PENDING,
                event_type="test",
                dedupe_key="retry-boundary",
                attempts=attempts,
                max_attempts=max_attempts,
                payload={},
            )
        )
    await session.rollback()


def test_idempotency_remains_unique_without_duplicate_index():
    table = ActionExecution.__table__
    assert any(
        isinstance(constraint, UniqueConstraint)
        and list(constraint.columns.keys()) == ["idempotency_key"]
        for constraint in table.constraints
    )
    assert all(list(index.columns.keys()) != ["idempotency_key"] for index in table.indexes)
    indexes = GitHubAutomationRecord.__table__.indexes
    assert any(list(index.columns.keys()) == ["incident_id", "created_at"] for index in indexes)
    assert all(list(index.columns.keys()) != ["incident_id"] for index in indexes)


def test_legacy_column_capacity_is_preserved():
    assert Approval.__table__.c.decision.type.length == 16
    assert Approval.__table__.c.environment.type.length == 32
    assert FinOpsRecommendation.__table__.c.environment.type.length == 32
    assert FinOpsRecommendation.__table__.c.status.type.length == 32
    assert SecurityEvent.__table__.c.source.type.length == 255
