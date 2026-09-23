"""Structured incident-memory persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IncidentMemoryRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "incident_memory"
    __table_args__ = (
        Index("ix_incident_memory_fingerprint", "fingerprint"),
        Index("ix_incident_memory_match", "service_key", "incident_type", "resolved_at"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="duration_nonnegative",
        ),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("incidents.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    service_key: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(128), nullable=False)
    alert_name: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str | None] = mapped_column(String(253))
    root_cause_category: Mapped[str | None] = mapped_column(String(128))
    stable_labels: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    runbook_id: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_success: Mapped[bool | None] = mapped_column(Boolean)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    operator_summary: Mapped[str | None] = mapped_column(Text)
