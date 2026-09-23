"""Part 2 normalized runtime security and quarantine lifecycle records.

Revision ID: d2a7f1c4e903
Revises: 8b4f2d1c7a90
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7f1c4e903"
down_revision: str | Sequence[str] | None = "8b4f2d1c7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("security_events", sa.Column("incident_id", sa.Uuid(), nullable=True))
    op.add_column("security_events", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "security_events",
        sa.Column(
            "environment",
            sa.Enum(
                "LOCAL",
                "STAGING",
                "PRODUCTION",
                name="security_event_environment",
                native_enum=False,
            ),
            server_default="STAGING",
            nullable=False,
        ),
    )
    op.add_column(
        "security_events",
        sa.Column("namespace", sa.String(253), server_default="unknown", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column("pod", sa.String(253), server_default="unknown", nullable=False),
    )
    op.add_column("security_events", sa.Column("workload", sa.String(253), nullable=True))
    op.add_column(
        "security_events",
        sa.Column("container_name", sa.String(253), server_default="unknown", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column("policy", sa.String(253), server_default="legacy", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column("evidence_ref", sa.String(2048), server_default="legacy", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "security_events",
        sa.Column("dedup_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("security_events", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column("security_events", sa.Column("policy_decision", sa.String(32), nullable=True))
    op.add_column(
        "security_events",
        sa.Column(
            "containment_status",
            sa.Enum(
                "NOT_PROPOSED",
                "PROPOSED",
                "AWAITING_APPROVAL",
                "APPLYING",
                "CONTAINED",
                "VERIFICATION_FAILED",
                "REMOVING",
                "REMOVED",
                name="containment_status",
                native_enum=False,
            ),
            server_default="NOT_PROPOSED",
            nullable=False,
        ),
    )
    # The original Part 1 table had no fingerprint. Existing rows receive a
    # stable value derived solely from their UUID before the uniqueness gate.
    op.execute(
        "UPDATE security_events SET fingerprint = "
        "replace(CAST(id AS VARCHAR), '-', '') WHERE fingerprint IS NULL"
    )
    op.execute(
        "UPDATE security_events SET event_type = 'SUSPICIOUS_PROCESS' "
        "WHERE event_type NOT IN "
        "('SUSPICIOUS_PROCESS', 'UNEXPECTED_EGRESS', 'PRIVILEGE_BEHAVIOR')"
    )
    op.alter_column("security_events", "fingerprint", nullable=False)
    op.alter_column(
        "security_events",
        "event_type",
        existing_type=sa.String(128),
        type_=sa.Enum(
            "SUSPICIOUS_PROCESS",
            "UNEXPECTED_EGRESS",
            "PRIVILEGE_BEHAVIOR",
            name="security_event_category",
            native_enum=False,
        ),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "fk_security_events_incident_id_incidents",
        "security_events",
        "incidents",
        ["incident_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_security_events_source_fingerprint", "security_events", ["source", "fingerprint"]
    )
    op.create_index("ix_security_events_incident_id", "security_events", ["incident_id"])
    op.create_index("ix_security_events_occurred_at", "security_events", ["occurred_at"])

    op.create_table(
        "quarantine_records",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("security_event_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(253), nullable=False),
        sa.Column("pod", sa.String(253), nullable=False),
        sa.Column("workload", sa.String(253), nullable=True),
        sa.Column("policy_name", sa.String(253), nullable=False),
        sa.Column("selector", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("opa_decision", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NOT_PROPOSED",
                "PROPOSED",
                "AWAITING_APPROVAL",
                "APPLYING",
                "CONTAINED",
                "VERIFICATION_FAILED",
                "REMOVING",
                "REMOVED",
                name="quarantine_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("verification", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["security_event_id"], ["security_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_name"),
    )
    op.create_index(
        "ix_quarantine_records_incident_created",
        "quarantine_records",
        ["incident_id", "created_at"],
    )
    op.create_index("ix_quarantine_records_incident_id", "quarantine_records", ["incident_id"])
    op.create_index(
        "ix_quarantine_records_security_event_id", "quarantine_records", ["security_event_id"]
    )
    op.create_index("ix_quarantine_records_status", "quarantine_records", ["status"])


def downgrade() -> None:
    op.drop_index("ix_quarantine_records_status", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_security_event_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_incident_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_incident_created", table_name="quarantine_records")
    op.drop_table("quarantine_records")
    op.drop_index("ix_security_events_occurred_at", table_name="security_events")
    op.drop_index("ix_security_events_incident_id", table_name="security_events")
    op.drop_constraint("uq_security_events_source_fingerprint", "security_events", type_="unique")
    op.drop_constraint(
        "fk_security_events_incident_id_incidents", "security_events", type_="foreignkey"
    )
    op.alter_column(
        "security_events",
        "event_type",
        existing_type=sa.Enum(
            "SUSPICIOUS_PROCESS",
            "UNEXPECTED_EGRESS",
            "PRIVILEGE_BEHAVIOR",
            name="security_event_category",
            native_enum=False,
        ),
        type_=sa.String(128),
        existing_nullable=False,
    )
    op.drop_column("security_events", "containment_status")
    op.drop_column("security_events", "policy_decision")
    op.drop_column("security_events", "risk_score")
    op.drop_column("security_events", "dedup_count")
    op.drop_column("security_events", "last_seen_at")
    op.drop_column("security_events", "occurred_at")
    op.drop_column("security_events", "evidence_ref")
    op.drop_column("security_events", "policy")
    op.drop_column("security_events", "container_name")
    op.drop_column("security_events", "workload")
    op.drop_column("security_events", "pod")
    op.drop_column("security_events", "namespace")
    op.drop_column("security_events", "environment")
    op.drop_column("security_events", "fingerprint")
    op.drop_column("security_events", "incident_id")
