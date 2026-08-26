"""Incident memory input and factual API response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.remediation.actions import ActionType


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    service: str = Field(min_length=1, max_length=255)
    environment: str = Field(min_length=1, max_length=32)
    incident_type: str = Field(min_length=1, max_length=128)
    alert_name: str = Field(min_length=1, max_length=255)
    namespace: str | None = Field(default=None, max_length=253)
    root_cause_category: str | None = Field(default=None, max_length=128)
    labels: dict[str, str] = Field(default_factory=dict)
    runbook_id: str | None = Field(default=None, max_length=255)
    action: ActionType | None = None
    result: str = Field(min_length=1, max_length=64)
    verification_success: bool | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    model: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    resolved_at: datetime
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    operator_summary: str | None = Field(default=None, max_length=2000)


class SimilarIncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    incident_id: uuid.UUID
    fingerprint: str
    match_score: int = Field(ge=0, le=100)
    match_reasons: list[str]
    service: str
    environment: str
    incident_type: str
    alert_name: str
    root_cause_category: str | None
    runbook_id: str | None
    action: ActionType | None
    result: str
    verification_success: bool | None
    duration_seconds: int | None
    model: str | None
    confidence: float | None
    successful: bool
    resolved_at: datetime
    evidence_summary: dict[str, Any]
    operator_summary: str | None
