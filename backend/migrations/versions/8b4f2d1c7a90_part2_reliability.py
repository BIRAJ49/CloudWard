"""Part 2 reliability, alert, verification, and Incident Lab records.

Revision ID: 8b4f2d1c7a90
Revises: 4692cc9cb2ee
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b4f2d1c7a90"
down_revision: str | Sequence[str] | None = "4692cc9cb2ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column(
            "resolution_source",
            sa.Enum(
                "CLOUDWARD_REMEDIATION",
                "PLATFORM_SELF_HEALING",
                "HUMAN_ACTION",
                "EXTERNAL_SYSTEM",
                "UNKNOWN",
                name="resolution_source",
                native_enum=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("evidence_snapshots", sa.Column("query", sa.Text(), nullable=True))
    op.add_column(
        "evidence_snapshots",
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evidence_snapshots",
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evidence_snapshots",
        sa.Column(
            "phase",
            sa.Enum("BEFORE", "INCIDENT", "AFTER", name="evidence_phase", native_enum=False),
            server_default="INCIDENT",
            nullable=False,
        ),
    )
    op.add_column(
        "action_executions", sa.Column("idempotency_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "action_executions",
        sa.Column("rollback_of_execution_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "action_executions",
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_action_executions_idempotency_key", "action_executions", ["idempotency_key"]
    )
    op.create_index(
        "ix_action_executions_idempotency_key",
        "action_executions",
        ["idempotency_key"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_action_executions_rollback_of_execution_id_action_executions",
        "action_executions",
        "action_executions",
        ["rollback_of_execution_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "alert_records",
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("alert_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("FIRING", "RESOLVED", name="alert_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("service", sa.String(length=255), nullable=False),
        sa.Column(
            "environment",
            sa.Enum("LOCAL", "STAGING", "PRODUCTION", name="alert_environment", native_enum=False),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(length=253), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "fingerprint"),
    )
    op.create_index("ix_alert_records_incident_id", "alert_records", ["incident_id"])
    op.create_index(
        "ix_alert_records_status_last_received",
        "alert_records",
        ["status", "last_received_at"],
    )

    op.create_table(
        "verification_records",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("action_execution_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("before_values", sa.JSON(), nullable=False),
        sa.Column("after_values", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt >= 1 AND attempt <= 3", name="ck_verification_records_verification_attempt_range"
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"], ["action_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id", "attempt"),
    )
    op.create_index(
        "ix_verification_records_incident_id", "verification_records", ["incident_id"]
    )

    op.create_table(
        "chaos_executions",
        sa.Column("scenario_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "STOPPING",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                "CANCELLED",
                name="experiment_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("target_namespace", sa.String(length=253), nullable=False),
        sa.Column("target_selector", sa.JSON(), nullable=False),
        sa.Column("expected_alert", sa.String(length=128), nullable=False),
        sa.Column("expected_runbook", sa.String(length=255), nullable=False),
        sa.Column("resource_kind", sa.String(length=64), nullable=True),
        sa.Column("resource_name", sa.String(length=253), nullable=True),
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=False),
        sa.Column("cleanup_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chaos_executions_scenario_id", "chaos_executions", ["scenario_id"])
    op.create_index(
        "ix_chaos_executions_status_created", "chaos_executions", ["status", "created_at"]
    )

    op.create_table(
        "stream_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stream_events_created_at", "stream_events", ["created_at"])
    op.create_index("ix_stream_events_incident_id", "stream_events", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_stream_events_incident_id", table_name="stream_events")
    op.drop_index("ix_stream_events_created_at", table_name="stream_events")
    op.drop_table("stream_events")
    op.drop_index("ix_chaos_executions_status_created", table_name="chaos_executions")
    op.drop_index("ix_chaos_executions_scenario_id", table_name="chaos_executions")
    op.drop_table("chaos_executions")
    op.drop_index("ix_verification_records_incident_id", table_name="verification_records")
    op.drop_table("verification_records")
    op.drop_index("ix_alert_records_status_last_received", table_name="alert_records")
    op.drop_index("ix_alert_records_incident_id", table_name="alert_records")
    op.drop_table("alert_records")
    op.drop_constraint(
        "fk_action_executions_rollback_of_execution_id_action_executions",
        "action_executions",
        type_="foreignkey",
    )
    op.drop_index("ix_action_executions_idempotency_key", table_name="action_executions")
    op.drop_constraint(
        "uq_action_executions_idempotency_key", "action_executions", type_="unique"
    )
    op.drop_column("action_executions", "rolled_back_at")
    op.drop_column("action_executions", "rollback_of_execution_id")
    op.drop_column("action_executions", "idempotency_key")
    op.drop_column("evidence_snapshots", "phase")
    op.drop_column("evidence_snapshots", "window_end")
    op.drop_column("evidence_snapshots", "window_start")
    op.drop_column("evidence_snapshots", "query")
    op.drop_column("incidents", "resolution_source")
