"""Strict data contracts crossing the model trust boundary."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.remediation.actions import ActionType


class AIOperation(StrEnum):
    DIAGNOSE_INCIDENT = "diagnose_incident"
    SUMMARIZE_EVIDENCE = "summarize_evidence"
    CORRELATE_CHANGE = "correlate_change"
    SUGGEST_ACTIONS = "suggest_actions"


class AIStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"


class RelatedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=255)
    commit_sha: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    files: list[str] = Field(default_factory=list, max_length=20)
    correlation: str = Field(min_length=1, max_length=1000)

    @field_validator("files")
    @classmethod
    def validate_files(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 500 for item in value):
            raise ValueError("change file references must contain 1-500 characters")
        return value


class DiagnosisProposal(BaseModel):
    """Operator-facing model output; no executable text is accepted."""

    model_config = ConfigDict(extra="forbid")

    suspected_root_cause: str = Field(min_length=1, max_length=1000)
    root_cause_category: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    confidence: float = Field(ge=0.0, le=1.0, strict=True)
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    related_change: RelatedChange | None = None
    suggested_runbook: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$",
    )
    action_candidates: list[ActionType] = Field(default_factory=list, max_length=5)
    explanation: str = Field(min_length=1, max_length=2000)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("evidence_refs must be unique")
        if any(not item or len(item) > 255 for item in value):
            raise ValueError("evidence references must contain 1-255 characters")
        return value

    @field_validator("action_candidates")
    @classmethod
    def validate_action_candidates(cls, value: list[ActionType]) -> list[ActionType]:
        if len(set(value)) != len(value):
            raise ValueError("action candidates must be unique")
        return value


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class ChangeCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correlated: bool
    confidence: float = Field(ge=0.0, le=1.0, strict=True)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=1, max_length=1500)


class ActionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_candidates: list[ActionType] = Field(default_factory=list, max_length=5)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=1, max_length=1500)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    operation: AIOperation
    requested_model: str
    actual_model: str
    output: DiagnosisProposal | EvidenceSummary | ChangeCorrelation | ActionSuggestion
    latency_ms: int = Field(ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class InvocationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_model: str
    actual_model: str | None = None
    success: bool
    fallback: bool = False
    escalation: bool = False
    latency_ms: int = Field(default=0, ge=0)
    error_code: str | None = None


class DiagnosisOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AIStatus
    proposal: DiagnosisProposal | None = None
    model_used: str | None = None
    fallback_used: bool = False
    escalation_used: bool = False
    attempts: list[InvocationAttempt] = Field(default_factory=list, max_length=3)
    failure_code: str | None = None

    @model_validator(mode="after")
    def validate_status_contract(self) -> DiagnosisOutcome:
        if self.status == AIStatus.AVAILABLE and self.proposal is None:
            raise ValueError("available outcome requires a proposal")
        if self.status == AIStatus.AI_UNAVAILABLE and self.proposal is not None:
            raise ValueError("unavailable outcome cannot contain a proposal")
        return self


class StoredDiagnosisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: AIStatus | Literal["NOT_REQUESTED"]
    suspected_root_cause: str | None = None
    root_cause_category: str | None = None
    confidence: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    related_change: dict[str, Any] | None = None
    suggested_runbook: str | None = None
    action_candidates: list[ActionType] = Field(default_factory=list)
    explanation: str | None = None
    model_used: str | None = None
    fallback_used: bool = False
    escalation_used: bool = False
    created_at: str | None = None


class AIActionEvaluationRequest(BaseModel):
    """Bounded target facts used to gate one model-suggested action."""

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    target_count: int = Field(default=1, ge=1, le=1000)
    namespace: str | None = Field(
        default=None,
        min_length=1,
        max_length=253,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    resource_name: str | None = Field(default=None, min_length=1, max_length=253)
    labels: dict[str, str] = Field(default_factory=dict)
    controller_managed: bool = True
    sensitivity: Literal["none", "low", "moderate", "high"] = "none"

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 30:
            raise ValueError("labels must contain at most 30 entries")
        if any(
            not key or not item or len(key) > 253 or len(item) > 253
            for key, item in value.items()
        ):
            raise ValueError("label keys and values must contain 1-253 characters")
        return value


class AIActionEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_id: uuid.UUID
    proposal_id: uuid.UUID
    action: ActionType
    risk_score: int = Field(ge=0, le=100)
    risk_classification: str
    policy_allowed: bool
    requires_approval: bool
    policy_reason: str
    proposal_status: str
    advisory_only: Literal[True] = True
    execution_started: Literal[False] = False
