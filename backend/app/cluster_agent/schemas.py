from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.finops.schemas import CostAllocation
from app.observability.providers import TelemetryResult

KubernetesName = Annotated[
    str, Field(min_length=1, max_length=253, pattern=r"^[a-z0-9][a-z0-9.-]*$")
]


class AgentTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    namespace: Literal["cloudward-staging", "cloudward-production"]
    service: KubernetesName
    deployment: KubernetesName


class PodObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: KubernetesName
    phase: Literal["Pending", "Running", "Succeeded", "Failed", "Unknown"]
    ready: bool
    restarts: int = Field(ge=0, le=1_000_000)


class DeploymentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    generation: int = Field(ge=1)
    observed_generation: int = Field(ge=0)
    desired_replicas: int = Field(ge=0, le=100_000)
    ready_replicas: int = Field(ge=0, le=100_000)
    updated_replicas: int = Field(ge=0, le=100_000)
    pods: list[PodObservation] = Field(max_length=50)
    truncated: bool = False


class WorkloadReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target: AgentTarget
    deployment: DeploymentObservation | None = None
    telemetry: list[TelemetryResult] = Field(default_factory=list, max_length=5)
    cost: CostAllocation | None = None
    errors: list[Annotated[str, Field(pattern=r"^[A-Z_]{1,64}$")]] = Field(
        default_factory=list, max_length=8
    )

    @model_validator(mode="after")
    def bounded_evidence(self) -> WorkloadReport:
        if self.deployment is None and not self.errors:
            raise ValueError("missing Kubernetes evidence must include a collection error")
        for item in self.telemetry:
            if item.provider not in {"prometheus", "loki", "tempo"} or len(item.samples) > 10:
                raise ValueError("unsupported or oversized telemetry evidence")
            if len(item.query) > 2000:
                raise ValueError("telemetry query is too long")
        return self


class AgentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    report_id: uuid.UUID
    cluster_id: uuid.UUID
    observed_at: datetime
    workloads: list[WorkloadReport] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def consistent_observations(self) -> AgentReport:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        targets = [(item.target.namespace, item.target.service) for item in self.workloads]
        if len(set(targets)) != len(targets):
            raise ValueError("duplicate workload targets")
        for workload in self.workloads:
            for item in workload.telemetry:
                if abs((item.window.end - self.observed_at).total_seconds()) > 120:
                    raise ValueError("telemetry window must belong to this observation")
        return self


class AgentReceipt(BaseModel):
    report_id: uuid.UUID
    duplicate: bool
    attached_incidents: int
    status: Literal["CONNECTED", "DEGRADED"]
