"""Bounded latest cluster-agent observation.

Revision ID: 52a7c9d1e402
Revises: 31b7e2f4a901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "52a7c9d1e402"
down_revision: str | Sequence[str] | None = "31b7e2f4a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cluster_agent_states",
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("report_digest", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("cluster_id"),
    )


def downgrade() -> None:
    op.drop_table("cluster_agent_states")
