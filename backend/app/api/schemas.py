from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    ActorType,
    AlertStatus,
    Environment,
    EvidencePhase,
    RecordStatus,
    ResolutionSource,
)
from app.evidence.types import EvidenceType
from app.incidents.state_machine import IncidentState
from app.remediation.actions import ActionType


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=4000)
    environment: Environment
    service_id: uuid.UUID | None = None
    cluster_id: uuid.UUID | None = None


class IncidentTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: IncidentState
    reason: str | None = Field(default=None, max_length=1000)


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    correlation_id: str
    incident_type: str
    title: str
    summary: str | None
    environment: Environment
    state: IncidentState
    severity: str
    risk_score: int | None
    retry_count: int
    runbook_id: str | None
    runbook_version: int | None
    service_id: uuid.UUID | None
    cluster_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolution_source: ResolutionSource | None


class IncidentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    event_type: str
    from_state: IncidentState | None
    to_state: IncidentState | None
    actor: str
    actor_type: ActorType
    details: dict[str, Any]
    correlation_id: str
    created_at: datetime


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evidence_type: EvidenceType
    summary: str
    reference: str | None
    query: str | None
    window_start: datetime | None
    window_end: datetime | None
    phase: EvidencePhase
    payload: dict[str, Any]
    created_at: datetime


class ActionProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action_type: ActionType
    parameters: dict[str, Any]
    status: RecordStatus
    risk_score: int
    risk_calculation: dict[str, Any]
    created_at: datetime


class ActionExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    proposal_id: uuid.UUID
    action_type: ActionType
    attempt: int
    status: RecordStatus
    result: dict[str, Any]
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    rollback_of_execution_id: uuid.UUID | None
    rolled_back_at: datetime | None


class VerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action_execution_id: uuid.UUID | None
    attempt: int
    success: bool
    checks: list[dict[str, Any]]
    before_values: dict[str, Any]
    after_values: dict[str, Any]
    started_at: datetime
    completed_at: datetime


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    alert_name: str
    status: AlertStatus
    severity: str
    service: str
    environment: Environment
    namespace: str | None
    starts_at: datetime
    ends_at: datetime | None
    last_received_at: datetime
    repeat_count: int


class PolicyDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    allowed: bool
    requires_approval: bool
    reason: str
    result: dict[str, Any]
    created_at: datetime


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor: str
    actor_type: ActorType
    event_type: str
    action: str | None
    risk_score: int | None
    policy_decision: str | None
    result: str
    event_metadata: dict[str, Any]
    correlation_id: str
    created_at: datetime


class IncidentDetailResponse(IncidentResponse):
    events: list[IncidentEventResponse]
    evidence: list[EvidenceResponse]
    actions: list[ActionProposalResponse]
    executions: list[ActionExecutionResponse]
    verifications: list[VerificationResponse]
    alerts: list[AlertResponse]
    policy_decisions: list[PolicyDecisionResponse]
    audit_events: list[AuditResponse]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=1000)


class TaskPublishResponse(BaseModel):
    task_id: str
    task_name: str
    queue: str
