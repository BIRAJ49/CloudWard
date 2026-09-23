"""Align historical constraint names and remove a redundant lookup index.

Revision ID: 64b9e0a3f215
Revises: 52a7c9d1e402

Rename checks in place: no safety constraints or application records are dropped.
The unique idempotency constraint already supplies the same B-tree lookup index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "64b9e0a3f215"
down_revision: str | Sequence[str] | None = "52a7c9d1e402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = (
    (
        "ai_diagnoses",
        "ck_ai_diagnoses_ck_ai_diagnoses_confidence_range",
        "ck_ai_diagnoses_confidence_range",
    ),
    (
        "incident_memory",
        "ck_incident_memory_ck_incident_memory_confidence_range",
        "ck_incident_memory_confidence_range",
    ),
    (
        "incident_memory",
        "ck_incident_memory_ck_incident_memory_duration_nonnegative",
        "ck_incident_memory_duration_nonnegative",
    ),
    (
        "verification_records",
        "ck_verification_records_ck_verification_records_verific_372e",
        "ck_verification_records_verification_attempt_range",
    ),
)


def upgrade() -> None:
    for table, previous, current in _CHECKS:
        # All identifiers are fixed migration literals, not external input.
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{previous}" TO "{current}"')
    op.drop_index("ix_action_executions_idempotency_key", table_name="action_executions")
    # Part 3 backfilled lowercase environment values, while SQLAlchemy stores enum names.
    op.execute(
        "UPDATE finops_recommendations SET environment = upper(environment) "
        "WHERE environment IN ('local', 'staging', 'production')"
    )


def downgrade() -> None:
    op.create_index(
        "ix_action_executions_idempotency_key", "action_executions", ["idempotency_key"]
    )
    for table, previous, current in reversed(_CHECKS):
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{current}" TO "{previous}"')
    # Keep canonical environment names: reverting them would break ORM reads.
