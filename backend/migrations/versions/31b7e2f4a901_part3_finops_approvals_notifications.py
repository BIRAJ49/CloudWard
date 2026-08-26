"""Part 3 deterministic FinOps, stale-safe approvals, and notifications.

Revision ID: 31b7e2f4a901
Revises: 31a1c9d8e201
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "31b7e2f4a901"
down_revision: str | Sequence[str] | None = "31a1c9d8e201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _upgrade_finops()
    _upgrade_approvals()
    _upgrade_notifications()


def _upgrade_finops() -> None:
    op.add_column("finops_recommendations", sa.Column("service", sa.String(253), nullable=True))
    op.add_column(
        "finops_recommendations", sa.Column("environment", sa.String(32), nullable=True)
    )
    op.add_column(
        "finops_recommendations",
        sa.Column("current_config", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "finops_recommendations",
        sa.Column("recommended_config", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "finops_recommendations",
        sa.Column("evidence", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "finops_recommendations",
        sa.Column("estimated_savings", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column("finops_recommendations", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column("finops_recommendations", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "finops_recommendations",
        sa.Column("limitations", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "finops_recommendations", sa.Column("evidence_window_start", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "finops_recommendations", sa.Column("evidence_window_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "finops_recommendations", sa.Column("source_fingerprint", sa.String(64), nullable=True)
    )
    op.add_column(
        "finops_recommendations",
        sa.Column("proposal_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "finops_recommendations", sa.Column("expected_state_digest", sa.String(64), nullable=True)
    )
    op.add_column(
        "finops_recommendations", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("finops_recommendations", sa.Column("pr_reference", sa.String(255), nullable=True))
    op.add_column("finops_recommendations", sa.Column("pr_url", sa.String(2048), nullable=True))
    op.add_column(
        "finops_recommendations", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "finops_recommendations", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE finops_recommendations SET "
        "service = 'legacy', environment = 'local', risk_score = 100, confidence = 0, "
        "evidence_window_start = created_at, evidence_window_end = created_at, "
        "source_fingerprint = replace(CAST(id AS VARCHAR), '-', '') || "
        "'00000000000000000000000000000000', "
        "expected_state_digest = replace(CAST(id AS VARCHAR), '-', '') || "
        "'00000000000000000000000000000000', expires_at = created_at, "
        "status = 'DETECTED' WHERE service IS NULL"
    )
    for column in (
        "service",
        "environment",
        "risk_score",
        "confidence",
        "evidence_window_start",
        "evidence_window_end",
        "source_fingerprint",
        "expected_state_digest",
        "expires_at",
    ):
        op.alter_column("finops_recommendations", column, nullable=False)
    op.create_unique_constraint(
        "uq_finops_recommendations_source_fingerprint",
        "finops_recommendations",
        ["source_fingerprint"],
    )
    op.create_index(
        "ix_finops_status_created", "finops_recommendations", ["status", "created_at"]
    )
    op.create_check_constraint(
        "finops_risk_score_range",
        "finops_recommendations",
        "risk_score >= 0 AND risk_score <= 100",
    )
    op.create_check_constraint(
        "finops_confidence_range",
        "finops_recommendations",
        "confidence >= 0 AND confidence <= 1",
    )


def _upgrade_approvals() -> None:
    columns: tuple[sa.Column, ...] = (
        sa.Column("action", sa.String(128), nullable=True),
        sa.Column("environment", sa.String(32), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("blast_radius", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reversible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("runbook", sa.String(255), nullable=True),
        sa.Column("proposal_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("target_reference", sa.String(1024), nullable=True),
        sa.Column("expected_state", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("context_digest", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
        sa.Column("execution_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_reference", sa.String(255), nullable=True),
    )
    for column in columns:
        op.add_column("approvals", column)
    op.execute(
        "UPDATE approvals AS a SET "
        "action = p.action_type, environment = i.environment, risk_score = p.risk_score, "
        "requested_by = 'legacy', runbook = i.runbook_id, "
        "target_reference = 'legacy/unknown', "
        "context_digest = replace(CAST(a.id AS VARCHAR), '-', '') || "
        "'00000000000000000000000000000000', expires_at = a.created_at, "
        "decided_at = a.updated_at, decision_comment = a.reason "
        "FROM action_proposals AS p, incidents AS i "
        "WHERE a.proposal_id = p.id AND a.incident_id = i.id"
    )
    op.execute(
        "WITH ranked AS ("
        "SELECT id, row_number() OVER (PARTITION BY proposal_id ORDER BY created_at, id) AS version "
        "FROM approvals) "
        "UPDATE approvals AS a SET proposal_version = ranked.version "
        "FROM ranked WHERE a.id = ranked.id"
    )
    for column in (
        "action",
        "environment",
        "risk_score",
        "requested_by",
        "target_reference",
        "context_digest",
        "expires_at",
    ):
        op.alter_column("approvals", column, nullable=False)
    op.create_unique_constraint(
        "uq_approvals_proposal_version", "approvals", ["proposal_id", "proposal_version"]
    )
    op.create_index("ix_approvals_decision", "approvals", ["decision"])
    op.create_check_constraint(
        "approval_risk_score_range", "approvals", "risk_score >= 0 AND risk_score <= 100"
    )
    op.create_check_constraint(
        "approval_proposal_version_positive", "approvals", "proposal_version >= 1"
    )


def _upgrade_notifications() -> None:
    op.add_column("notifications", sa.Column("event_type", sa.String(128), nullable=True))
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(128), nullable=True))
    op.add_column(
        "notifications", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "notifications", sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False)
    )
    op.add_column("notifications", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE notifications SET event_type = 'legacy', "
        "dedupe_key = replace(CAST(id AS VARCHAR), '-', '') WHERE event_type IS NULL"
    )
    op.alter_column("notifications", "event_type", nullable=False)
    op.alter_column("notifications", "dedupe_key", nullable=False)
    op.create_unique_constraint(
        "uq_notifications_channel_dedupe_key", "notifications", ["channel", "dedupe_key"]
    )
    op.create_check_constraint(
        "notification_attempts_nonnegative", "notifications", "attempts >= 0"
    )
    op.create_check_constraint(
        "notification_max_attempts_positive", "notifications", "max_attempts >= 1"
    )


def downgrade() -> None:
    op.drop_constraint("notification_max_attempts_positive", "notifications", type_="check")
    op.drop_constraint("notification_attempts_nonnegative", "notifications", type_="check")
    op.drop_constraint(
        "uq_notifications_channel_dedupe_key", "notifications", type_="unique"
    )
    for column in (
        "next_attempt_at",
        "delivered_at",
        "last_error",
        "max_attempts",
        "attempts",
        "dedupe_key",
        "event_type",
    ):
        op.drop_column("notifications", column)

    op.drop_constraint("approval_proposal_version_positive", "approvals", type_="check")
    op.drop_constraint("approval_risk_score_range", "approvals", type_="check")
    op.drop_index("ix_approvals_decision", table_name="approvals")
    op.drop_constraint("uq_approvals_proposal_version", "approvals", type_="unique")
    for column in (
        "execution_reference",
        "execution_claimed_at",
        "invalidated_reason",
        "decision_comment",
        "decided_by",
        "decided_at",
        "expires_at",
        "context_digest",
        "expected_state",
        "target_reference",
        "proposal_version",
        "runbook",
        "requested_by",
        "reversible",
        "blast_radius",
        "risk_score",
        "environment",
        "action",
    ):
        op.drop_column("approvals", column)

    op.drop_constraint("finops_confidence_range", "finops_recommendations", type_="check")
    op.drop_constraint("finops_risk_score_range", "finops_recommendations", type_="check")
    op.drop_index("ix_finops_status_created", table_name="finops_recommendations")
    op.drop_constraint(
        "uq_finops_recommendations_source_fingerprint",
        "finops_recommendations",
        type_="unique",
    )
    for column in (
        "rejected_at",
        "approved_at",
        "pr_url",
        "pr_reference",
        "expires_at",
        "expected_state_digest",
        "proposal_version",
        "source_fingerprint",
        "evidence_window_end",
        "evidence_window_start",
        "limitations",
        "confidence",
        "risk_score",
        "estimated_savings",
        "evidence",
        "recommended_config",
        "current_config",
        "environment",
        "service",
    ):
        op.drop_column("finops_recommendations", column)
