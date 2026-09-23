"""One bounded latest observation per registered cluster; incident evidence is separate."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClusterAgentState(Base):
    __tablename__ = "cluster_agent_states"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clusters.id", ondelete="RESTRICT"), primary_key=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    report_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
