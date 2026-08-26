"""Strict schemas for normalized, bounded runtime-security telemetry."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import ContainmentStatus, Environment, SecurityCategory

KUBERNETES_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
EVIDENCE_REFERENCE = re.compile(r"^tetragon:[A-Za-z0-9._:/-]{1,500}$")


class ProcessDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binary: str = Field(min_length=1, max_length=512)
    parent_binary: str | None = Field(default=None, max_length=512)


class NetworkDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination_host: str = Field(min_length=1, max_length=253)
    destination_port: int = Field(ge=1, le=65_535)
    protocol: Literal["tcp", "udp"] = "tcp"


class TetragonSecurityEvent(BaseModel):
    """The forwarder emits this allowlisted schema, never a raw Tetragon object."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["tetragon"]
    event_type: SecurityCategory
    severity: Literal["info", "warning", "high", "critical"]
    environment: Environment
    namespace: str = Field(min_length=1, max_length=253)
    pod: str = Field(min_length=1, max_length=253)
    workload: str | None = Field(default=None, max_length=253)
    container: str = Field(min_length=1, max_length=253)
    process: ProcessDetails | None = None
    network: NetworkDetails | None = None
    policy: str = Field(min_length=1, max_length=253)
    timestamp: datetime
    evidence_ref: str = Field(min_length=1, max_length=512)
    workload_labels: dict[str, str] = Field(default_factory=dict, max_length=12)
    secrets_or_data_exposure: bool = False

    @field_validator("namespace", "pod", "container", "workload")
    @classmethod
    def validate_kubernetes_name(cls, value: str | None) -> str | None:
        if value is not None and not KUBERNETES_NAME.fullmatch(value):
            raise ValueError("invalid Kubernetes resource name")
        return value

    @field_validator("evidence_ref")
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not EVIDENCE_REFERENCE.fullmatch(value):
            raise ValueError("evidence_ref must be an opaque Tetragon reference")
        return value

    @field_validator("workload_labels")
    @classmethod
    def bound_labels(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {
            "cloudward.io/demo-target",
            "cloudward.io/environment",
            "cloudward.io/criticality",
            "app.kubernetes.io/name",
        }
        if any(key not in allowed for key in value):
            raise ValueError("workload_labels contains an unsupported label")
        if any(len(key) > 128 or len(item) > 128 for key, item in value.items()):
            raise ValueError("workload label is too large")
        return value

    @model_validator(mode="after")
    def category_matches_policy_and_evidence(self) -> TetragonSecurityEvent:
        expected = {
            "cloudward-s1-unexpected-shell": SecurityCategory.SUSPICIOUS_PROCESS,
            "cloudward-s2-unexpected-egress": SecurityCategory.UNEXPECTED_EGRESS,
            "cloudward-s3-privilege-attempt": SecurityCategory.PRIVILEGE_BEHAVIOR,
        }
        if expected.get(self.policy) != self.event_type:
            raise ValueError("event type does not match an allowlisted TracingPolicy")
        if self.namespace != "cloudward-staging" or self.environment != Environment.STAGING:
            raise ValueError("Part 2 runtime telemetry is restricted to cloudward-staging")
        if self.workload_labels.get("cloudward.io/demo-target") != "true":
            raise ValueError("runtime telemetry target is outside the demo safety boundary")
        if self.event_type == SecurityCategory.UNEXPECTED_EGRESS and self.network is None:
            raise ValueError("unexpected egress requires normalized network details")
        if self.event_type != SecurityCategory.UNEXPECTED_EGRESS and self.process is None:
            raise ValueError("process or privilege events require normalized process details")
        return self


class SecurityEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: SecurityCategory
    severity: str
    environment: Environment
    namespace: str
    pod: str
    workload: str | None
    container: str
    policy: str
    evidence_ref: str
    incident_id: uuid.UUID | None
    containment_status: ContainmentStatus
    risk_score: int | None
    policy_decision: str | None
    occurred_at: datetime
    last_seen_at: datetime
    dedup_count: int
    process: ProcessDetails | None = None
    network: NetworkDetails | None = None


class SecurityWebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    queued: bool
    duplicate: bool | None = None
    fingerprint: str = Field(min_length=64, max_length=64)
    task_id: str | None = None
    event: SecurityEventResponse | None = None


class SecurityJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fingerprint: str = Field(min_length=64, max_length=64)
    event: TetragonSecurityEvent


class QuarantineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    security_event_id: uuid.UUID
    namespace: str
    pod: str
    workload: str | None
    policy_name: str
    status: ContainmentStatus
    risk_score: int
    opa_decision: str
    verification: dict[str, object]
    applied_at: datetime | None
    removed_at: datetime | None
