"""Part 3 advisory AI, GitHub automation, and structured incident memory.

Revision ID: 31a1c9d8e201
Revises: d2a7f1c4e903
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "31a1c9d8e201"
down_revision: str | Sequence[str] | None = "d2a7f1c4e903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_diagnoses",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("suspected_root_cause", sa.Text(), nullable=True),
        sa.Column("root_cause_category", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("related_change", sa.JSON(), nullable=True),
        sa.Column("suggested_runbook", sa.String(255), nullable=True),
        sa.Column("action_candidates", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("escalation_used", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_diagnoses_confidence_range",
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_diagnoses_incident_created",
        "ai_diagnoses",
        ["incident_id", "created_at"],
    )

    op.create_table(
        "incident_memory",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("service_key", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("incident_type", sa.String(128), nullable=False),
        sa.Column("alert_name", sa.String(255), nullable=False),
        sa.Column("namespace", sa.String(253), nullable=True),
        sa.Column("root_cause_category", sa.String(128), nullable=True),
        sa.Column("stable_labels", sa.JSON(), nullable=False),
        sa.Column("runbook_id", sa.String(255), nullable=True),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("result", sa.String(64), nullable=False),
        sa.Column("verification_success", sa.Boolean(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_summary", sa.JSON(), nullable=False),
        sa.Column("operator_summary", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_incident_memory_confidence_range",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_incident_memory_duration_nonnegative",
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index("ix_incident_memory_fingerprint", "incident_memory", ["fingerprint"])
    op.create_index(
        "ix_incident_memory_match",
        "incident_memory",
        ["service_key", "incident_type", "resolved_at"],
    )

    op.create_table(
        "github_automation_records",
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("repository", sa.String(255), nullable=False),
        sa.Column("external_number", sa.Integer(), nullable=True),
        sa.Column("external_url", sa.String(2048), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_github_automation_incident",
        "github_automation_records",
        ["incident_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_github_automation_incident", table_name="github_automation_records")
    op.drop_table("github_automation_records")
    op.drop_index("ix_incident_memory_match", table_name="incident_memory")
    op.drop_index("ix_incident_memory_fingerprint", table_name="incident_memory")
    op.drop_table("incident_memory")
    op.drop_index("ix_ai_diagnoses_incident_created", table_name="ai_diagnoses")
    op.drop_table("ai_diagnoses")
