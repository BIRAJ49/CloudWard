"""Collection, persistence, lifecycle, and GitOps proposal orchestration for FinOps."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.base import utc_now
from app.db.models import (
    ActorType,
    Environment,
    FinOpsRecommendation,
    FinOpsStatus,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.finops.engine import FinOpsEngine, FinOpsPolicy
from app.finops.providers import OpenCostClient, PrometheusFinOpsClient
from app.finops.schemas import AnalysisResult, GitOpsChangeProposal

F1 = "finops.overprovisioned-workload"
F2 = "finops.wasted-node-capacity"
FINOPS_SCENARIOS = frozenset({F1, F2})


def _digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class FinOpsRecommendationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.engine = FinOpsEngine(
            FinOpsPolicy(
                cpu_headroom_factor=settings.finops_cpu_headroom_factor,
                memory_headroom_factor=settings.finops_memory_headroom_factor,
                minimum_cpu_cores=settings.finops_minimum_cpu_millicores / 1000,
                minimum_memory_bytes=settings.finops_minimum_memory_mib * 1024 * 1024,
                minimum_reduction_fraction=settings.finops_minimum_reduction_percent / 100,
                minimum_samples=settings.finops_minimum_samples,
                minimum_demo_window_seconds=settings.finops_demo_minimum_window_seconds,
                minimum_production_window_seconds=settings.finops_production_minimum_window_seconds,
                minimum_coverage=settings.finops_minimum_window_coverage,
                node_request_utilization_threshold=settings.finops_node_request_threshold,
                node_actual_utilization_threshold=settings.finops_node_usage_threshold,
            )
        )
        self.opencost = OpenCostClient(
            str(settings.opencost_url),
            timeout_seconds=settings.finops_provider_timeout_seconds,
            max_response_bytes=settings.finops_max_response_bytes,
        )
        self.prometheus = PrometheusFinOpsClient(
            str(settings.prometheus_url),
            timeout_seconds=settings.finops_provider_timeout_seconds,
            max_response_bytes=settings.finops_max_response_bytes,
            max_samples=settings.finops_max_samples,
        )

    async def analyze_scenario(
        self,
        scenario_id: str,
        *,
        actor: str,
        actor_type: ActorType = ActorType.USER,
    ) -> tuple[AnalysisResult, FinOpsRecommendation | None]:
        if scenario_id not in FINOPS_SCENARIOS:
            raise CloudWardError(
                "FINOPS_SCENARIO_NOT_FOUND",
                "FinOps scenario is not in the fixed catalog",
                status_code=404,
            )
        environment = Environment.STAGING
        window_seconds = self.settings.finops_demo_observation_window_seconds
        if scenario_id == F1:
            allocation = await self.opencost.workload_allocation(
                namespace=self.settings.finops_demo_namespace,
                deployment=self.settings.finops_demo_deployment,
                window_seconds=window_seconds,
            )
            workload_observation = await self.prometheus.collect_workload(
                namespace=self.settings.finops_demo_namespace,
                deployment=self.settings.finops_demo_deployment,
                pod_pattern=self.settings.finops_demo_pod_pattern,
                environment=environment.value,
                window_seconds=window_seconds,
                step_seconds=self.settings.finops_query_step_seconds,
                allocation=allocation,
            )
            result = self.engine.analyze_workload(workload_observation)
        else:
            allocation = await self.opencost.cluster_allocation(window_seconds=window_seconds)
            node_observation = await self.prometheus.collect_nodes(
                environment=environment.value,
                window_seconds=window_seconds,
                step_seconds=self.settings.finops_query_step_seconds,
                allocation=allocation,
            )
            result = self.engine.analyze_nodes(node_observation)
        recommendation = await self.persist_result(
            result,
            actor=actor,
            actor_type=actor_type,
        )
        return result, recommendation

    async def persist_result(
        self,
        result: AnalysisResult,
        *,
        actor: str,
        actor_type: ActorType,
    ) -> FinOpsRecommendation | None:
        if result.recommendation is None:
            await record_audit(
                self.session,
                event_type="FINOPS_ANALYSIS_COMPLETED",
                correlation_id=f"finops-{result.scenario_id}",
                actor=actor,
                actor_type=actor_type,
                action=result.scenario_id,
                result=result.outcome,
                metadata={"reason": result.reason, "deterministic": True},
            )
            return None
        draft = result.recommendation
        existing = (
            await self.session.execute(
                select(FinOpsRecommendation).where(
                    FinOpsRecommendation.source_fingerprint == draft.source_fingerprint
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        expected_state_digest = _digest(draft.current_config)
        recommendation = FinOpsRecommendation(
            service=draft.service,
            environment=Environment(draft.environment),
            recommendation_type=draft.recommendation_type,
            status=FinOpsStatus.RECOMMENDED,
            estimated_monthly_savings=None,
            current_config=draft.current_config,
            recommended_config=draft.recommended_config,
            evidence=draft.evidence,
            estimated_savings=draft.estimated_savings,
            risk_score=draft.risk_score,
            confidence=draft.confidence,
            limitations=list(draft.limitations),
            evidence_window_start=draft.evidence_window.start,
            evidence_window_end=draft.evidence_window.end,
            source_fingerprint=draft.source_fingerprint,
            proposal_version=1,
            expected_state_digest=expected_state_digest,
            expires_at=utc_now()
            + timedelta(seconds=self.settings.finops_recommendation_ttl_seconds),
            details={
                "why": draft.why,
                "scenario_id": result.scenario_id,
                "deterministic": True,
                "ai_calculated": False,
                "data_period": draft.evidence_window.model_dump(mode="json"),
            },
        )
        self.session.add(recommendation)
        await self.session.flush()
        await record_audit(
            self.session,
            event_type="FINOPS_RECOMMENDATION_GENERATED",
            correlation_id=f"finops-{recommendation.id}",
            actor=actor,
            actor_type=actor_type,
            action=draft.recommendation_type,
            risk_score=draft.risk_score,
            result="RECOMMENDED",
            metadata={
                "recommendation_id": str(recommendation.id),
                "confidence": draft.confidence,
                "source_fingerprint": draft.source_fingerprint,
                "evidence_window_start": draft.evidence_window.start.isoformat(),
                "evidence_window_end": draft.evidence_window.end.isoformat(),
                "deterministic": True,
            },
        )
        await append_stream_event(
            self.session,
            event_type="finops.recommendation",
            incident_id=None,
            payload={
                "recommendation_id": str(recommendation.id),
                "recommendation_type": recommendation.recommendation_type,
                "service": recommendation.service,
                "environment": recommendation.environment.value,
                "status": recommendation.status.value,
                "risk_score": recommendation.risk_score,
                "confidence": recommendation.confidence,
            },
        )
        return recommendation

    async def get_for_update(self, recommendation_id: uuid.UUID) -> FinOpsRecommendation:
        recommendation = (
            await self.session.execute(
                select(FinOpsRecommendation)
                .where(FinOpsRecommendation.id == recommendation_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if recommendation is None:
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_NOT_FOUND",
                "FinOps recommendation was not found",
                status_code=404,
            )
        if recommendation.expires_at <= utc_now() and recommendation.status not in {
            FinOpsStatus.APPROVED,
            FinOpsStatus.REJECTED,
            FinOpsStatus.APPLIED,
            FinOpsStatus.VERIFIED,
            FinOpsStatus.EXPIRED,
        }:
            recommendation.status = FinOpsStatus.EXPIRED
            await record_audit(
                self.session,
                event_type="FINOPS_RECOMMENDATION_EXPIRED",
                correlation_id=f"finops-{recommendation.id}",
                action=recommendation.recommendation_type,
                risk_score=recommendation.risk_score,
                result="EXPIRED",
                metadata={"recommendation_id": str(recommendation.id)},
            )
        return recommendation

    def build_gitops_proposal(self, recommendation: FinOpsRecommendation) -> GitOpsChangeProposal:
        if recommendation.recommendation_type != "WORKLOAD_RIGHTSIZING":
            raise CloudWardError(
                "FINOPS_PR_NOT_APPLICABLE",
                "Only a workload rightsizing recommendation can produce this GitOps change",
                status_code=409,
            )
        if recommendation.status not in {FinOpsStatus.RECOMMENDED, FinOpsStatus.PR_CREATED}:
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_NOT_PROPOSABLE",
                "Recommendation is not in a PR-proposable state",
                status_code=409,
            )
        if recommendation.expires_at <= utc_now():
            recommendation.status = FinOpsStatus.EXPIRED
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_EXPIRED",
                "Recommendation evidence expired before PR creation",
                status_code=409,
            )
        if _digest(recommendation.current_config) != recommendation.expected_state_digest:
            recommendation.status = FinOpsStatus.EXPIRED
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_STALE",
                "Recommendation current state no longer matches its bound proposal version",
                status_code=409,
            )
        requests = recommendation.recommended_config.get("requests")
        if not isinstance(requests, dict):
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_INVALID",
                "Recommendation has no typed resource requests",
                status_code=409,
            )
        cpu_cores = float(requests["cpu_cores"])
        memory_bytes = int(requests["memory_bytes"])
        cpu = f"{math_ceil(cpu_cores * 1000)}m"
        memory = f"{math_ceil(memory_bytes / (1024 * 1024))}Mi"
        content = (
            "# Created by CloudWard; human review and merge are required.\n"
            f"recommendationId: {recommendation.id}\n"
            f"proposalVersion: {recommendation.proposal_version}\n"
            "resources:\n"
            "  requests:\n"
            f'    cpu: "{cpu}"\n'
            f'    memory: "{memory}"\n'
        )
        current = json.dumps(recommendation.current_config, sort_keys=True, indent=2)
        proposed = json.dumps(recommendation.recommended_config, sort_keys=True, indent=2)
        savings = json.dumps(recommendation.estimated_savings, sort_keys=True)
        body = (
            "Created by CloudWard\n\n"
            f"Recommendation: `{recommendation.id}` (version {recommendation.proposal_version})\n\n"
            f"Reason: {recommendation.details.get('why', 'Deterministic rightsizing analysis')}\n\n"
            f"Current state:\n```json\n{current}\n```\n\n"
            f"Proposed state:\n```json\n{proposed}\n```\n\n"
            f"Estimated impact: `{savings}`\n\n"
            f"Risk: {recommendation.risk_score}/100; confidence: {recommendation.confidence:.2f}\n\n"
            f"Evidence window: {recommendation.evidence_window_start.isoformat()} to "
            f"{recommendation.evidence_window_end.isoformat()}\n\n"
            "Verification plan: observe CPU/memory p95, restarts, readiness, latency, and errors after rollout.\n\n"
            "Rollback plan: revert this pull request to restore the previous resource requests.\n\n"
            "CloudWard will not merge this pull request or resize the live production Deployment."
        )
        return GitOpsChangeProposal(
            repository=self.settings.finops_gitops_repository,
            branch_prefix=f"cloudward/finops-{recommendation.id.hex[:12]}",
            path=self.settings.finops_gitops_values_path,
            title=f"CloudWard: rightsize {recommendation.service}",
            body=body,
            content=content,
            recommendation_id=str(recommendation.id),
            expected_state_digest=recommendation.expected_state_digest,
        )

    def patch_gitops_values(
        self,
        recommendation: FinOpsRecommendation,
        existing_content: str,
    ) -> str:
        """Patch only fixed request keys after matching the observed state."""

        try:
            document = yaml.safe_load(existing_content)
        except yaml.YAMLError as exc:
            raise CloudWardError(
                "FINOPS_GITOPS_VALUES_INVALID",
                "Allowlisted GitOps values are not valid YAML",
                status_code=409,
            ) from exc
        if not isinstance(document, dict):
            raise CloudWardError(
                "FINOPS_GITOPS_VALUES_INVALID",
                "Allowlisted GitOps values are not an object",
                status_code=409,
            )
        workload = document.get("cloudward-demo")
        if not isinstance(workload, dict):
            raise CloudWardError(
                "FINOPS_GITOPS_TARGET_MISSING",
                "Fixed cloudward-demo values target is missing",
                status_code=409,
            )
        resources = workload.get("resources")
        requests = resources.get("requests") if isinstance(resources, dict) else None
        if not isinstance(requests, dict):
            raise CloudWardError(
                "FINOPS_GITOPS_TARGET_MISSING",
                "Fixed resource requests target is missing",
                status_code=409,
            )
        current_requests = recommendation.current_config.get("requests")
        proposed_requests = recommendation.recommended_config.get("requests")
        if not isinstance(current_requests, dict) or not isinstance(proposed_requests, dict):
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_INVALID",
                "Recommendation resource requests are invalid",
                status_code=409,
            )
        current_cpu = _parse_cpu(requests.get("cpu"))
        current_memory = _parse_memory(requests.get("memory"))
        expected_cpu = float(current_requests["cpu_cores"])
        expected_memory = int(current_requests["memory_bytes"])
        if abs(current_cpu - expected_cpu) > 0.001 or current_memory != expected_memory:
            recommendation.status = FinOpsStatus.EXPIRED
            raise CloudWardError(
                "FINOPS_RECOMMENDATION_STALE",
                "GitOps resource requests changed after recommendation evidence collection",
                status_code=409,
            )
        requests["cpu"] = f"{math_ceil(float(proposed_requests['cpu_cores']) * 1000)}m"
        requests["memory"] = (
            f"{math_ceil(int(proposed_requests['memory_bytes']) / (1024 * 1024))}Mi"
        )
        rendered = yaml.safe_dump(document, sort_keys=False)
        if not isinstance(rendered, str):
            raise TypeError("YAML serializer returned a non-text result")
        return rendered

    async def record_pr_created(
        self,
        recommendation: FinOpsRecommendation,
        *,
        pr_reference: str,
        pr_url: str,
        actor: str,
    ) -> None:
        if recommendation.pr_reference and recommendation.pr_reference != pr_reference:
            raise CloudWardError(
                "FINOPS_PR_ALREADY_CREATED",
                "A different pull request is already bound to this recommendation",
                status_code=409,
            )
        recommendation.status = FinOpsStatus.PR_CREATED
        recommendation.pr_reference = pr_reference
        recommendation.pr_url = pr_url
        await record_audit(
            self.session,
            event_type="FINOPS_GITHUB_PR_CREATED",
            correlation_id=f"finops-{recommendation.id}",
            actor=actor,
            actor_type=ActorType.USER,
            action="CREATE_GITOPS_PR",
            risk_score=recommendation.risk_score,
            result="SUCCEEDED",
            metadata={
                "recommendation_id": str(recommendation.id),
                "pr_reference": pr_reference,
                "approval_authority": "GITHUB_PULL_REQUEST",
            },
        )
        await append_stream_event(
            self.session,
            event_type="finops.pr_created",
            incident_id=None,
            payload={
                "recommendation_id": str(recommendation.id),
                "status": recommendation.status.value,
                "pr_reference": pr_reference,
                "pr_url": pr_url,
            },
        )


def math_ceil(value: float) -> int:
    # Kept local so generated YAML always rounds safety quantities upward.
    import math

    return math.ceil(value)


def _parse_cpu(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.endswith("m"):
        try:
            return float(value[:-1]) / 1000
        except ValueError:
            pass
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CloudWardError(
            "FINOPS_GITOPS_QUANTITY_INVALID", "GitOps CPU request is invalid", status_code=409
        ) from exc


def _parse_memory(value: Any) -> int:
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3}
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        for suffix, multiplier in units.items():
            if value.endswith(suffix):
                try:
                    return round(float(value[: -len(suffix)]) * multiplier)
                except ValueError:
                    break
    raise CloudWardError(
        "FINOPS_GITOPS_QUANTITY_INVALID", "GitOps memory request is invalid", status_code=409
    )
