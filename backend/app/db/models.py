"""Core persistence model for the Part 1 modular monolith.

Historical records use restrictive or nulling foreign keys and are never cascade-deleted.
Incident events and audit events are append-oriented at the application boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from app.evidence.types import EvidenceType
from app.incidents.state_machine import IncidentState
from app.rbac.policy import Role
from app.remediation.actions import ActionType


def enum_type(enum_class: type[StrEnum], name: str, *, length: int | None = None) -> Enum:
    options = {} if length is None else {"length": length}
    return Enum(enum_class, name=name, native_enum=False, validate_strings=True, **options)


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    SERVICE = "SERVICE"


class RecordStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SecurityCategory(StrEnum):
    SUSPICIOUS_PROCESS = "SUSPICIOUS_PROCESS"
    UNEXPECTED_EGRESS = "UNEXPECTED_EGRESS"
    PRIVILEGE_BEHAVIOR = "PRIVILEGE_BEHAVIOR"


class ContainmentStatus(StrEnum):
    NOT_PROPOSED = "NOT_PROPOSED"
    PROPOSED = "PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPLYING = "APPLYING"
    CONTAINED = "CONTAINED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REMOVING = "REMOVING"
    REMOVED = "REMOVED"


class ResolutionSource(StrEnum):
    CLOUDWARD_REMEDIATION = "CLOUDWARD_REMEDIATION"
    PLATFORM_SELF_HEALING = "PLATFORM_SELF_HEALING"
    HUMAN_ACTION = "HUMAN_ACTION"
    EXTERNAL_SYSTEM = "EXTERNAL_SYSTEM"
    UNKNOWN = "UNKNOWN"


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class EvidencePhase(StrEnum):
    BEFORE = "BEFORE"
    INCIDENT = "INCIDENT"
    AFTER = "AFTER"


class ExperimentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class FinOpsStatus(StrEnum):
    DETECTED = "DETECTED"
    ANALYZED = "ANALYZED"
    RECOMMENDED = "RECOMMENDED"
    PR_CREATED = "PR_CREATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class ApprovalDecision(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    github_login: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    identities: Mapped[list[OAuthIdentity]] = relationship(back_populates="user")
    role_mappings: Mapped[list[RoleMapping]] = relationship(
        back_populates="user", foreign_keys="RoleMapping.user_id"
    )


class OAuthIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "external_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_login: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="identities")


class RoleMapping(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "role_mappings"
    __table_args__ = (UniqueConstraint("user_id", "scope"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[Role] = mapped_column(enum_type(Role, "role"), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="global")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))

    user: Mapped[User] = relationship(back_populates="role_mappings", foreign_keys=[user_id])


class Cluster(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "clusters"
    __table_args__ = (UniqueConstraint("name", "environment"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "environment"), nullable=False
    )
    context_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Service(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("cluster_id", "namespace", "name"),)

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clusters.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    deployment_name: Mapped[str] = mapped_column(String(253), nullable=False)
    health_url: Mapped[str | None] = mapped_column(String(2048))
    criticality: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    cluster: Mapped[Cluster] = relationship()


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("retry_count >= 0 AND retry_count <= 3", name="retry_count_range"),
        Index("ix_incidents_state_created_at", "state", "created_at"),
    )

    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clusters.id", ondelete="SET NULL"), index=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "incident_environment"), nullable=False
    )
    state: Mapped[IncidentState] = mapped_column(
        enum_type(IncidentState, "incident_state"),
        nullable=False,
        default=IncidentState.DETECTED,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    risk_score: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runbook_id: Mapped[str | None] = mapped_column(String(255))
    runbook_version: Mapped[int | None] = mapped_column(Integer)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_source: Mapped[ResolutionSource | None] = mapped_column(
        enum_type(ResolutionSource, "resolution_source")
    )

    cluster: Mapped[Cluster | None] = relationship()
    service: Mapped[Service | None] = relationship()
    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", order_by="IncidentEvent.created_at"
    )


class IncidentEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_created", "incident_id", "created_at"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[IncidentState | None] = mapped_column(
        enum_type(IncidentState, "incident_event_from_state")
    )
    to_state: Mapped[IncidentState | None] = mapped_column(
        enum_type(IncidentState, "incident_event_to_state")
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType, "incident_actor_type"), nullable=False
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    incident: Mapped[Incident] = relationship(back_populates="events")


class EvidenceSnapshot(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "evidence_snapshots"
    __table_args__ = (Index("ix_evidence_incident_created", "incident_id", "created_at"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        enum_type(EvidenceType, "evidence_type"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(2048))
    query: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phase: Mapped[EvidencePhase] = mapped_column(
        enum_type(EvidencePhase, "evidence_phase"),
        nullable=False,
        default=EvidencePhase.INCIDENT,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    collected_by: Mapped[str] = mapped_column(String(255), nullable=False, default="cloudward")


class Diagnosis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "diagnoses"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="deterministic")
    classification: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ActionProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "action_proposals"
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="risk_score_range"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(
        enum_type(ActionType, "action_type"), nullable=False
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus, "proposal_status"), nullable=False, default=RecordStatus.PENDING
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_calculation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="cloudward")


class ActionExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "action_executions"
    __table_args__ = (
        UniqueConstraint("incident_id", "attempt"),
        UniqueConstraint("idempotency_key"),
        CheckConstraint("attempt >= 1 AND attempt <= 3", name="attempt_range"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(
        enum_type(ActionType, "execution_action_type"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus, "execution_status"), nullable=False
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    rollback_of_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("action_executions.id", ondelete="RESTRICT")
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "alert_records"
    __table_args__ = (
        UniqueConstraint("source", "fingerprint"),
        Index("ix_alert_records_status_last_received", "status", "last_received_at"),
    )

    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="prometheus")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    alert_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus, "alert_status"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "alert_environment"), nullable=False
    )
    namespace: Mapped[str | None] = mapped_column(String(253))
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VerificationRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "verification_records"
    __table_args__ = (
        UniqueConstraint("incident_id", "attempt"),
        CheckConstraint("attempt >= 1 AND attempt <= 3", name="verification_attempt_range"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("action_executions.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    before_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    after_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ChaosExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chaos_executions"
    __table_args__ = (Index("ix_chaos_executions_status_created", "status", "created_at"),)

    scenario_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[ExperimentStatus] = mapped_column(
        enum_type(ExperimentStatus, "experiment_status"),
        nullable=False,
        default=ExperimentStatus.PENDING,
    )
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    target_namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    target_selector: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    expected_alert: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_runbook: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_kind: Mapped[str | None] = mapped_column(String(64))
    resource_name: Mapped[str | None] = mapped_column(String(253))
    max_runtime_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cleanup_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class StreamEvent(Base):
    __tablename__ = "stream_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Approval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("proposal_id", "proposal_version", name="uq_approvals_proposal_version"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="approval_risk_score_range"),
        CheckConstraint("proposal_version >= 1", name="approval_proposal_version_positive"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decision: Mapped[ApprovalDecision] = mapped_column(
        enum_type(ApprovalDecision, "approval_decision", length=16),
        nullable=False,
        default=ApprovalDecision.PENDING,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "approval_environment", length=32), nullable=False
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    blast_radius: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    runbook: Mapped[str | None] = mapped_column(String(255))
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    expected_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    execution_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_reference: Mapped[str | None] = mapped_column(String(255))


class PolicyDecision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "policy_decisions"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_path: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Runbook(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "runbooks"
    __table_args__ = (UniqueConstraint("runbook_id", "version"),)

    runbook_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)


class RunbookExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "runbook_executions"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    runbook_id: Mapped[str] = mapped_column(String(255), nullable=False)
    runbook_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus, "runbook_execution_status"), nullable=False
    )
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class SecurityEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "security_events"

    __table_args__ = (
        UniqueConstraint("source", "fingerprint", name="uq_security_events_source_fingerprint"),
        Index("ix_security_events_occurred_at", "occurred_at"),
    )

    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[SecurityCategory] = mapped_column(
        enum_type(SecurityCategory, "security_event_category"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "security_event_environment"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    pod: Mapped[str] = mapped_column(String(253), nullable=False)
    workload: Mapped[str | None] = mapped_column(String(253))
    container_name: Mapped[str] = mapped_column(String(253), nullable=False)
    policy: Mapped[str] = mapped_column(String(253), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    risk_score: Mapped[int | None] = mapped_column(Integer)
    policy_decision: Mapped[str | None] = mapped_column(String(32))
    containment_status: Mapped[ContainmentStatus] = mapped_column(
        enum_type(ContainmentStatus, "containment_status"),
        nullable=False,
        default=ContainmentStatus.NOT_PROPOSED,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class QuarantineRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "quarantine_records"
    __table_args__ = (
        Index("ix_quarantine_records_incident_created", "incident_id", "created_at"),
        Index("ix_quarantine_records_status", "status"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    security_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("security_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    pod: Mapped[str] = mapped_column(String(253), nullable=False)
    workload: Mapped[str | None] = mapped_column(String(253))
    policy_name: Mapped[str] = mapped_column(String(253), nullable=False, unique=True)
    selector: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    opa_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ContainmentStatus] = mapped_column(
        enum_type(ContainmentStatus, "quarantine_status"), nullable=False
    )
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinOpsRecommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "finops_recommendations"
    __table_args__ = (
        UniqueConstraint("source_fingerprint", name="uq_finops_recommendations_source_fingerprint"),
        Index("ix_finops_status_created", "status", "created_at"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="finops_risk_score_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="finops_confidence_range"),
    )

    cluster_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clusters.id"))
    service: Mapped[str] = mapped_column(String(253), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_type(Environment, "finops_environment", length=32), nullable=False
    )
    recommendation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[FinOpsStatus] = mapped_column(
        enum_type(FinOpsStatus, "finops_status", length=32),
        nullable=False,
        default=FinOpsStatus.DETECTED,
    )
    estimated_monthly_savings: Mapped[float | None] = mapped_column(Float)
    current_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    recommended_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    estimated_savings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expected_state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pr_reference: Mapped[str | None] = mapped_column(String(255))
    pr_url: Mapped[str | None] = mapped_column(String(2048))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("channel", "dedupe_key", name="uq_notifications_channel_dedupe_key"),
        CheckConstraint("attempts >= 0", name="notification_attempts_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="notification_max_attempts_positive"),
    )

    incident_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("incidents.id"))
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus, "notification_status"), nullable=False
    )
    destination_reference: Mapped[str | None] = mapped_column(String(1024))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ModelInvocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_invocations"

    incident_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("incidents.id"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_incident_created", "incident_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType, "audit_actor_type"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str | None] = mapped_column(String(128))
    risk_score: Mapped[int | None] = mapped_column(Integer)
    policy_decision: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
