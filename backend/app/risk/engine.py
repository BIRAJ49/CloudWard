"""Auditable deterministic risk calculations. Risk never grants permission."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.remediation.actions import ActionType, get_action_metadata


class RiskClassification(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecommendedMode(StrEnum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCK_AND_ESCALATE = "BLOCK_AND_ESCALATE"


class Sensitivity(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class RiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str
    action: ActionType
    target_count: int = Field(default=1, ge=1)
    reversible: bool | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    sensitivity: Sensitivity = Sensitivity.NONE
    destructive_override: bool = False


class RiskFactors(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: int = Field(ge=0, le=15)
    blast_radius: int = Field(ge=0, le=25)
    destructiveness: int = Field(ge=0, le=20)
    reversibility: int = Field(ge=0, le=15)
    uncertainty: int = Field(ge=0, le=15)
    sensitivity: int = Field(ge=0, le=10)


class RiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: int = Field(ge=0, le=100)
    classification: RiskClassification
    recommended_mode: RecommendedMode
    factors: RiskFactors

    @model_validator(mode="after")
    def score_matches_factors(self) -> RiskResult:
        if self.score != sum(self.factors.model_dump().values()):
            raise ValueError("risk score must equal the factor sum")
        return self


DESTRUCTIVENESS: dict[ActionType, int] = {
    ActionType.DELETE_UNHEALTHY_POD: 3,
    ActionType.RESTART_POD: 3,
    ActionType.SCALE_STAGING_DEPLOYMENT: 5,
    ActionType.SCALE_WORKLOAD: 5,
    ActionType.REVERT_IMAGE: 8,
    ActionType.ROLLBACK_DEPLOYMENT: 8,
    ActionType.APPLY_QUARANTINE: 9,
    ActionType.QUARANTINE_WORKLOAD: 9,
    ActionType.REMOVE_QUARANTINE: 7,
    ActionType.CREATE_GITOPS_PR: 2,
    ActionType.CREATE_TERRAFORM_PR: 4,
    ActionType.CREATE_GITHUB_ISSUE: 0,
    ActionType.REQUEST_APPROVAL: 0,
    ActionType.NO_ACTION: 0,
}


class RiskEngine:
    @staticmethod
    def calculate(context: RiskContext) -> RiskResult:
        metadata = get_action_metadata(context.action)
        environment = {"local": 1, "development": 1, "staging": 4, "production": 15}.get(
            context.environment, 10
        )
        if context.target_count == 1:
            blast_radius = 3
        elif context.target_count <= 3:
            blast_radius = 8
        elif context.target_count <= 10:
            blast_radius = 15
        else:
            blast_radius = 25
        destructiveness = 20 if context.destructive_override else DESTRUCTIVENESS[context.action]
        reversible = metadata.reversible if context.reversible is None else context.reversible
        reversibility = 2 if reversible else 15
        uncertainty = round((1 - context.confidence) * 15)
        sensitivity = {
            Sensitivity.NONE: 0,
            Sensitivity.LOW: 2,
            Sensitivity.MODERATE: 6,
            Sensitivity.HIGH: 10,
        }[context.sensitivity]
        factors = RiskFactors(
            environment=environment,
            blast_radius=blast_radius,
            destructiveness=destructiveness,
            reversibility=reversibility,
            uncertainty=uncertainty,
            sensitivity=sensitivity,
        )
        score = sum(factors.model_dump().values())
        if score <= 30:
            classification = RiskClassification.LOW
            mode = RecommendedMode.AUTO_EXECUTE
        elif score <= 69:
            classification = RiskClassification.MEDIUM
            mode = RecommendedMode.APPROVAL_REQUIRED
        else:
            classification = RiskClassification.HIGH
            mode = RecommendedMode.BLOCK_AND_ESCALATE
        return RiskResult(
            score=score, classification=classification, recommended_mode=mode, factors=factors
        )
