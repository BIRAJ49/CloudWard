"""Strict schema for version-controlled YAML runbooks."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.remediation.actions import ActionType, get_action_metadata


class RunbookEnvironment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class RequiredEvidence(StrEnum):
    KUBERNETES_STATE = "kubernetes_state"
    KUBERNETES_EVENT = "kubernetes_event"
    READINESS = "readiness"
    HEALTH_CHECK = "health_check"
    ERROR_RATE = "error_rate"
    LATENCY = "latency"
    CPU_SATURATION = "cpu_saturation"
    MEMORY_WORKING_SET = "memory_working_set"
    CONTAINER_TERMINATION = "container_termination"
    RESTART_COUNT = "restart_count"
    RESOURCE_CONFIGURATION = "resource_configuration"
    LOGS = "logs"
    TRACES = "traces"
    DEPLOYMENT_STATE = "deployment_state"
    PREVIOUS_REVISION = "previous_revision"
    RUNTIME_SECURITY_EVENT = "runtime_security_event"
    CILIUM_POLICY_STATE = "cilium_policy_state"
    CONTROLLED_EGRESS_PROBE = "controlled_egress_probe"


class MatchSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    conditions: list[str] = Field(min_length=1, max_length=20)


class EvidenceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required: list[RequiredEvidence] = Field(min_length=1, max_length=20)


class PreconditionsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_target_pods: int = Field(ge=1, le=10)
    controller_managed: bool


class ActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ActionType


class VerificationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout: str
    conditions: list[str] = Field(min_length=1, max_length=20)

    @field_validator("timeout")
    @classmethod
    def validate_duration(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[1-9]\d*)(?:s|m)", value):
            raise ValueError("timeout must be a positive duration such as 120s or 2m")
        seconds = int(value[:-1]) * (60 if value.endswith("m") else 1)
        if seconds > 600:
            raise ValueError("verification timeout cannot exceed 10 minutes")
        return value

    @property
    def timeout_seconds(self) -> int:
        return int(self.timeout[:-1]) * (60 if self.timeout.endswith("m") else 1)


class RollbackSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class RunbookDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=3, max_length=255, pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
    version: int = Field(ge=1)
    environments: list[RunbookEnvironment] = Field(min_length=1)
    match: MatchSchema
    evidence: EvidenceSchema
    preconditions: PreconditionsSchema
    action: ActionSchema
    verify: VerificationSchema
    rollback: RollbackSchema

    @model_validator(mode="after")
    def validate_action_contract(self) -> RunbookDocument:
        metadata = get_action_metadata(self.action.type)
        unsupported = {value.value for value in self.environments} - set(
            metadata.allowed_environments
        )
        if unsupported:
            unsupported_list = sorted(unsupported)
            raise ValueError(
                f"action {self.action.type.value} does not support environments {unsupported_list}"
            )
        if self.rollback.enabled and not metadata.rollback_capable:
            raise ValueError(f"action {self.action.type.value} has no rollback capability")
        return self
