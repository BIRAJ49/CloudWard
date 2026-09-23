"""Deduplicated references to GitHub App write operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GitHubAutomationRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "github_automation_records"
    __table_args__ = (Index("ix_github_automation_incident", "incident_id", "created_at"),)

    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT")
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    external_number: Mapped[int | None]
    external_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
