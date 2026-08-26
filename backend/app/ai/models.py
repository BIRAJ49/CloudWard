"""Persistence owned by the AI diagnosis domain."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIDiagnosisRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_diagnoses"
    __table_args__ = (
        Index("ix_ai_diagnoses_incident_created", "incident_id", "created_at"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    suspected_root_cause: Mapped[str | None] = mapped_column(Text)
    root_cause_category: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    related_change: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    suggested_runbook: Mapped[str | None] = mapped_column(String(255))
    action_candidates: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
