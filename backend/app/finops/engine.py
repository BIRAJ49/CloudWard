"""Pure deterministic rightsizing and node-efficiency calculations."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from app.finops.schemas import (
    AnalysisResult,
    NodeObservation,
    Percentiles,
    RecommendationDraft,
    UsageSeries,
    WorkloadObservation,
)

MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FinOpsPolicy:
    cpu_headroom_factor: float = 1.5
    memory_headroom_factor: float = 1.35
    minimum_cpu_cores: float = 0.05
    minimum_memory_bytes: int = 64 * MIB
    minimum_reduction_fraction: float = 0.20
    minimum_samples: int = 5
    minimum_demo_window_seconds: int = 900
    minimum_production_window_seconds: int = 604_800
    minimum_coverage: float = 0.80
    node_request_utilization_threshold: float = 0.45
    node_actual_utilization_threshold: float = 0.35


def _quantile(values: tuple[float, ...], quantile: float) -> float:
    ordered = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not ordered:
        raise ValueError("usage series has no finite non-negative values")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _percentiles(series: UsageSeries) -> Percentiles:
    return Percentiles(
        p50=_quantile(series.values, 0.50),
        p95=_quantile(series.values, 0.95),
        p99=_quantile(series.values, 0.99),
    )


def _round_cpu_up(value: float) -> float:
    return math.ceil(value * 100) / 100


def _round_memory_up(value: float) -> int:
    return math.ceil(value / MIB) * MIB


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class FinOpsEngine:
    """Calculates recommendations exclusively from normalized observed data."""

    def __init__(self, policy: FinOpsPolicy) -> None:
        self.policy = policy

    def analyze_workload(self, observation: WorkloadObservation) -> AnalysisResult:
        insufficient = self._window_problem(
            environment=observation.environment,
            requested_seconds=observation.window.requested_seconds,
            observed_seconds=observation.window.observed_seconds,
            sample_count=min(
                len(observation.cpu_usage_cores.values),
                len(observation.memory_usage_bytes.values),
            ),
        )
        observed = observation.model_dump(mode="json")
        if insufficient:
            return AnalysisResult(
                scenario_id="finops.overprovisioned-workload",
                outcome="INSUFFICIENT_DATA",
                reason=insufficient,
                observed=observed,
            )

        cpu = _percentiles(observation.cpu_usage_cores)
        memory = _percentiles(observation.memory_usage_bytes)
        recommended_cpu = min(
            observation.cpu_request_cores,
            _round_cpu_up(
                max(cpu.p95 * self.policy.cpu_headroom_factor, self.policy.minimum_cpu_cores)
            ),
        )
        recommended_memory = min(
            observation.memory_request_bytes,
            _round_memory_up(
                max(
                    memory.p95 * self.policy.memory_headroom_factor,
                    self.policy.minimum_memory_bytes,
                )
            ),
        )
        cpu_reduction = 1 - recommended_cpu / observation.cpu_request_cores
        memory_reduction = 1 - recommended_memory / observation.memory_request_bytes
        if cpu_reduction < self.policy.minimum_reduction_fraction:
            recommended_cpu = observation.cpu_request_cores
            cpu_reduction = 0.0
        if memory_reduction < self.policy.minimum_reduction_fraction:
            recommended_memory = observation.memory_request_bytes
            memory_reduction = 0.0
        if cpu_reduction == 0 and memory_reduction == 0:
            return AnalysisResult(
                scenario_id="finops.overprovisioned-workload",
                outcome="NO_RECOMMENDATION",
                reason="Observed p95 usage plus configured safety headroom does not support a safe reduction.",
                observed={**observed, "cpu_percentiles": cpu.model_dump(), "memory_percentiles": memory.model_dump()},
            )

        coverage = min(1.0, observation.window.observed_seconds / observation.window.requested_seconds)
        completeness = 1.0 if observation.allocation.total_cost is not None else 0.85
        confidence = round(min(0.99, coverage * completeness), 2)
        reduction = max(cpu_reduction, memory_reduction)
        risk = min(
            100,
            round(10 + reduction * 35 + (1 - confidence) * 25 + (20 if observation.environment == "production" else 0)),
        )
        savings_value: float | None = None
        if observation.allocation.cpu_cost is not None and observation.allocation.memory_cost is not None:
            savings_value = round(
                observation.allocation.cpu_cost * cpu_reduction
                + observation.allocation.memory_cost * memory_reduction,
                4,
            )
        limitations = [
            "The estimate uses the local OpenCost model and is not an AWS savings claim.",
            "A pull request requires human review; CloudWard will not resize a live production Deployment.",
        ]
        if observation.window.demo_oriented:
            limitations.append("The evidence window is shortened for the local demo and is not production-grade.")
        if savings_value is None:
            limitations.append("OpenCost did not provide CPU and memory cost components, so monetary savings are not estimated.")
        evidence = {
            "cpu_usage_cores": cpu.model_dump(),
            "memory_usage_bytes": memory.model_dump(),
            "replicas": observation.replicas,
            "allocation": observation.allocation.model_dump(),
            "queries": observation.source_queries,
            "headroom": {
                "cpu_factor": self.policy.cpu_headroom_factor,
                "memory_factor": self.policy.memory_headroom_factor,
                "minimum_cpu_cores": self.policy.minimum_cpu_cores,
                "minimum_memory_bytes": self.policy.minimum_memory_bytes,
            },
        }
        current = {
            "replicas": observation.replicas,
            "requests": {
                "cpu_cores": observation.cpu_request_cores,
                "memory_bytes": observation.memory_request_bytes,
            },
            "limits": {
                "cpu_cores": observation.cpu_limit_cores,
                "memory_bytes": observation.memory_limit_bytes,
            },
        }
        recommended = {
            "replicas": observation.replicas,
            "requests": {
                "cpu_cores": recommended_cpu,
                "memory_bytes": recommended_memory,
            },
            "limits": current["limits"],
        }
        fingerprint_payload = {
            "service": observation.service,
            "environment": observation.environment,
            "window": observation.window.model_dump(mode="json"),
            "current": current,
            "recommended": recommended,
            "evidence": evidence,
        }
        draft = RecommendationDraft(
            recommendation_type="WORKLOAD_RIGHTSIZING",
            service=observation.service,
            environment=observation.environment,
            why="Sustained p95 CPU and/or memory usage remains below the current request after deterministic safety headroom.",
            current_config=current,
            recommended_config=recommended,
            evidence=evidence,
            estimated_savings={
                "value": savings_value,
                "currency": observation.allocation.currency,
                "window": "observed",
                "model": observation.allocation.model,
                "is_aws_estimate": False,
            },
            risk_score=risk,
            confidence=confidence,
            limitations=tuple(limitations),
            evidence_window=observation.window,
            source_fingerprint=_digest(fingerprint_payload),
        )
        return AnalysisResult(
            scenario_id="finops.overprovisioned-workload",
            outcome="RECOMMENDED",
            reason=draft.why,
            recommendation=draft,
            observed=observed,
        )

    def analyze_nodes(self, observation: NodeObservation) -> AnalysisResult:
        insufficient = self._window_problem(
            environment=observation.environment,
            requested_seconds=observation.window.requested_seconds,
            observed_seconds=observation.window.observed_seconds,
            sample_count=min(
                len(observation.cpu_usage_cores.values),
                len(observation.memory_usage_bytes.values),
            ),
        )
        observed = observation.model_dump(mode="json")
        if insufficient:
            return AnalysisResult(
                scenario_id="finops.wasted-node-capacity",
                outcome="INSUFFICIENT_DATA",
                reason=insufficient,
                observed=observed,
            )
        cpu = _percentiles(observation.cpu_usage_cores)
        memory = _percentiles(observation.memory_usage_bytes)
        request_utilization = max(
            observation.requested_cpu_cores / observation.allocatable_cpu_cores,
            observation.requested_memory_bytes / observation.allocatable_memory_bytes,
        )
        actual_utilization = max(
            cpu.p95 / observation.allocatable_cpu_cores,
            memory.p95 / observation.allocatable_memory_bytes,
        )
        if (
            request_utilization >= self.policy.node_request_utilization_threshold
            or actual_utilization >= self.policy.node_actual_utilization_threshold
        ):
            return AnalysisResult(
                scenario_id="finops.wasted-node-capacity",
                outcome="NO_RECOMMENDATION",
                reason="Observed node requests or p95 usage do not meet the configured underutilization thresholds.",
                observed={
                    **observed,
                    "request_utilization": request_utilization,
                    "actual_p95_utilization": actual_utilization,
                },
            )
        confidence = round(
            min(0.95, observation.window.observed_seconds / observation.window.requested_seconds),
            2,
        )
        current = {
            "node_count": observation.node_count,
            "allocatable_cpu_cores": observation.allocatable_cpu_cores,
            "allocatable_memory_bytes": observation.allocatable_memory_bytes,
            "requested_cpu_cores": observation.requested_cpu_cores,
            "requested_memory_bytes": observation.requested_memory_bytes,
            "pod_count": observation.pod_count,
        }
        recommended = {
            "actions": [
                "Review whether the baseline node count can be reduced.",
                "Adjust future autoscaler/Karpenter capacity strategy after topology and disruption review.",
            ],
            "automatic_change": False,
        }
        evidence = {
            "cpu_usage_cores": cpu.model_dump(),
            "memory_usage_bytes": memory.model_dump(),
            "request_utilization": round(request_utilization, 4),
            "actual_p95_utilization": round(actual_utilization, 4),
            "allocation": observation.allocation.model_dump(),
            "queries": observation.source_queries,
        }
        draft = RecommendationDraft(
            recommendation_type="NODE_EFFICIENCY",
            service="cluster-capacity",
            environment=observation.environment,
            why="Both scheduled requests and observed p95 usage are below the configured node-efficiency thresholds.",
            current_config=current,
            recommended_config=recommended,
            evidence=evidence,
            estimated_savings={
                "value": None,
                "currency": observation.allocation.currency,
                "model": observation.allocation.model,
                "is_aws_estimate": False,
            },
            risk_score=min(100, 20 + (20 if observation.environment == "production" else 0)),
            confidence=confidence,
            limitations=(
                "No monetary savings are claimed because node topology and an avoidable-node price were not proven.",
                "The result uses a local OpenCost model and is not an AWS or EKS validation.",
                "CloudWard does not change node count or production infrastructure automatically.",
            ),
            evidence_window=observation.window,
            source_fingerprint=_digest(
                {
                    "environment": observation.environment,
                    "window": observation.window.model_dump(mode="json"),
                    "current": current,
                    "evidence": evidence,
                }
            ),
        )
        return AnalysisResult(
            scenario_id="finops.wasted-node-capacity",
            outcome="RECOMMENDED",
            reason=draft.why,
            recommendation=draft,
            observed=observed,
        )

    def _window_problem(
        self,
        *,
        environment: str,
        requested_seconds: int,
        observed_seconds: int,
        sample_count: int,
    ) -> str | None:
        required = (
            self.policy.minimum_production_window_seconds
            if environment == "production"
            else self.policy.minimum_demo_window_seconds
        )
        if requested_seconds < required:
            return f"The requested observation window is below the {required}-second minimum."
        if observed_seconds < requested_seconds * self.policy.minimum_coverage:
            return "Observed samples do not cover enough of the requested evidence window."
        if sample_count < self.policy.minimum_samples:
            return "Too few utilization samples were observed for a safe recommendation."
        return None
