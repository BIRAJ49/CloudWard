"""Strict input and output contracts for deterministic FinOps analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime
    end: datetime
    requested_seconds: int = Field(ge=60)
    observed_seconds: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    demo_oriented: bool

    @model_validator(mode="after")
    def valid_window(self) -> EvidenceWindow:
        if self.end <= self.start:
            raise ValueError("evidence window end must be after start")
        return self


class UsageSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    values: tuple[float, ...]
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None


class CostAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cost: float | None = Field(default=None, ge=0)
    cpu_cost: float | None = Field(default=None, ge=0)
    memory_cost: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    model: Literal["opencost-local"] = "opencost-local"


class WorkloadObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str = Field(min_length=1, max_length=253)
    environment: Literal["local", "staging", "production"]
    namespace: str = Field(min_length=1, max_length=253)
    deployment: str = Field(min_length=1, max_length=253)
    replicas: int = Field(ge=1)
    cpu_request_cores: float = Field(gt=0)
    cpu_limit_cores: float | None = Field(default=None, gt=0)
    memory_request_bytes: float = Field(gt=0)
    memory_limit_bytes: float | None = Field(default=None, gt=0)
    cpu_usage_cores: UsageSeries
    memory_usage_bytes: UsageSeries
    allocation: CostAllocation
    window: EvidenceWindow
    source_queries: dict[str, str]


class NodeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: Literal["local", "staging", "production"]
    node_count: int = Field(ge=1)
    allocatable_cpu_cores: float = Field(gt=0)
    allocatable_memory_bytes: float = Field(gt=0)
    requested_cpu_cores: float = Field(ge=0)
    requested_memory_bytes: float = Field(ge=0)
    cpu_usage_cores: UsageSeries
    memory_usage_bytes: UsageSeries
    pod_count: int = Field(ge=0)
    allocation: CostAllocation
    window: EvidenceWindow
    source_queries: dict[str, str]


class Percentiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    p50: float = Field(ge=0)
    p95: float = Field(ge=0)
    p99: float = Field(ge=0)


class RecommendationDraft(BaseModel):
    """A recommendation calculated without any AI/LLM input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_type: Literal["WORKLOAD_RIGHTSIZING", "NODE_EFFICIENCY"]
    service: str
    environment: Literal["local", "staging", "production"]
    why: str
    current_config: dict[str, Any]
    recommended_config: dict[str, Any]
    evidence: dict[str, Any]
    estimated_savings: dict[str, Any]
    risk_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    limitations: tuple[str, ...]
    evidence_window: EvidenceWindow
    source_fingerprint: str = Field(min_length=64, max_length=64)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: Literal["finops.overprovisioned-workload", "finops.wasted-node-capacity"]
    outcome: Literal["RECOMMENDED", "NO_RECOMMENDATION", "INSUFFICIENT_DATA"]
    reason: str
    recommendation: RecommendationDraft | None = None
    observed: dict[str, Any]


class GitOpsChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    branch_prefix: str
    path: str
    title: str
    body: str
    content: str
    recommendation_id: str
    expected_state_digest: str
    machine_generated: Literal[True] = True
