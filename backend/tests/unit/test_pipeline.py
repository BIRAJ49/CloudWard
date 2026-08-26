from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import ActionExecution, AuditEvent, Incident
from app.incidents.state_machine import IncidentState
from app.kubernetes.executor import (
    DeploymentState,
    PodDeletionResult,
    PodState,
    ServiceHealth,
)
from app.policies.opa import PolicyResult
from app.remediation.pipeline import UnhealthyPodPipeline, UnhealthyPodTarget
from app.runbooks import RunbookLoader


def make_pod(name: str, ready: bool) -> PodState:
    return PodState(
        namespace="cloudward-staging",
        name=name,
        phase="Running",
        ready=ready,
        labels={
            "cloudward.io/demo-target": "true",
            "app.kubernetes.io/name": "cloudward-demo",
        },
        controller_managed=True,
        controller_kind="ReplicaSet",
        restart_count=0,
    )


class PipelineKubernetes:
    def __init__(self, *, heals_after_delete: bool) -> None:
        self.heals_after_delete = heals_after_delete
        self.delete_calls = 0

    @property
    def healthy(self) -> bool:
        return self.heals_after_delete and self.delete_calls > 0

    async def get_deployment(self, namespace: str, name: str) -> DeploymentState:
        ready = 2 if self.healthy else 1
        return DeploymentState(namespace, name, 2, ready, ready, 1)

    async def get_pods(self, namespace: str, label_selector: str) -> list[PodState]:
        if self.healthy:
            return [make_pod("replacement-1", True), make_pod("healthy-2", True)]
        return [make_pod("unhealthy-1", False), make_pod("healthy-2", True)]

    async def get_pod_health(self, namespace: str, name: str) -> PodState:
        return make_pod(name, False)

    async def delete_pod(self, namespace: str, name: str) -> PodDeletionResult:
        self.delete_calls += 1
        return PodDeletionResult(namespace, name, True, True)

    async def get_service_health(
        self, namespace: str, service_name: str, path: str = "health/ready"
    ) -> ServiceHealth:
        return ServiceHealth(
            namespace,
            service_name,
            path,
            self.healthy,
            {"status": "ready" if self.healthy else "not_ready"},
        )


class StaticOPA:
    def __init__(self, result: PolicyResult) -> None:
        self.result = result
        self.inputs = []

    async def evaluate(self, policy_input):  # type: ignore[no-untyped-def]
        self.inputs.append(policy_input)
        return self.result


def loader() -> RunbookLoader:
    runbooks = RunbookLoader(Path(__file__).resolve().parents[3] / "runbooks")
    runbooks.load()
    return runbooks


def test_default_pipeline_target_matches_helm_contract() -> None:
    target = UnhealthyPodTarget()
    assert target.deployment == "cloudward-demo"
    assert target.service_name == "cloudward-demo"
    assert target.label_selector == "app.kubernetes.io/name=cloudward-demo"
    assert target.namespace == "cloudward-staging"


@pytest.mark.asyncio
async def test_successful_pipeline_resolves_only_after_all_verification(
    session, settings: Settings
) -> None:
    kubernetes = PipelineKubernetes(heals_after_delete=True)
    opa = StaticOPA(
        PolicyResult(allowed=True, requires_approval=False, reason="safe staging remediation")
    )
    pipeline = UnhealthyPodPipeline(
        session=session,
        kubernetes=kubernetes,  # type: ignore[arg-type]
        runbooks=loader(),
        opa=opa,  # type: ignore[arg-type]
        settings=settings,
    )
    outcome = await pipeline.run(UnhealthyPodTarget(), correlation_id="pipeline-success")
    assert outcome.state == IncidentState.RESOLVED
    assert outcome.verification is not None and outcome.verification.success
    assert kubernetes.delete_calls == 1
    assert opa.inputs[0].risk_score == sum(opa.inputs[0].risk_factors.model_dump().values())
    assert opa.inputs[0].target.namespace == "cloudward-staging"

    audit = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.incident_id == outcome.incident_id)
                .order_by(AuditEvent.created_at)
            )
        ).scalars()
    )
    event_types = {event.event_type for event in audit}
    assert {
        "INCIDENT_CREATED",
        "EVIDENCE_COLLECTED",
        "RUNBOOK_SELECTED",
        "ACTION_PROPOSED",
        "RISK_CALCULATED",
        "OPA_EVALUATED",
        "ACTION_EXECUTED",
        "VERIFICATION_COMPLETED",
        "INCIDENT_RESOLVED",
    }.issubset(event_types)


@pytest.mark.asyncio
async def test_policy_denial_blocks_without_execution(session, settings: Settings) -> None:
    kubernetes = PipelineKubernetes(heals_after_delete=True)
    opa = StaticOPA(PolicyResult(allowed=False, requires_approval=False, reason="denied"))
    outcome = await UnhealthyPodPipeline(
        session=session,
        kubernetes=kubernetes,  # type: ignore[arg-type]
        runbooks=loader(),
        opa=opa,  # type: ignore[arg-type]
        settings=settings,
    ).run(UnhealthyPodTarget(), correlation_id="pipeline-blocked")
    assert outcome.state == IncidentState.BLOCKED
    assert kubernetes.delete_calls == 0


@pytest.mark.asyncio
async def test_approval_requirement_stops_before_execution(session, settings: Settings) -> None:
    kubernetes = PipelineKubernetes(heals_after_delete=True)
    opa = StaticOPA(
        PolicyResult(allowed=False, requires_approval=True, reason="operator approval required")
    )
    outcome = await UnhealthyPodPipeline(
        session=session,
        kubernetes=kubernetes,  # type: ignore[arg-type]
        runbooks=loader(),
        opa=opa,  # type: ignore[arg-type]
        settings=settings,
    ).run(UnhealthyPodTarget(), correlation_id="pipeline-approval")
    assert outcome.state == IncidentState.AWAITING_APPROVAL
    assert kubernetes.delete_calls == 0
    audit_types = set(
        (
            await session.execute(
                select(AuditEvent.event_type).where(AuditEvent.incident_id == outcome.incident_id)
            )
        ).scalars()
    )
    assert "APPROVAL_REQUESTED" in audit_types


@pytest.mark.asyncio
async def test_failed_verification_retries_three_times_then_escalates(
    session, settings: Settings
) -> None:
    kubernetes = PipelineKubernetes(heals_after_delete=False)
    opa = StaticOPA(PolicyResult(allowed=True, requires_approval=False, reason="allowed"))
    outcome = await UnhealthyPodPipeline(
        session=session,
        kubernetes=kubernetes,  # type: ignore[arg-type]
        runbooks=loader(),
        opa=opa,  # type: ignore[arg-type]
        settings=settings,
    ).run(UnhealthyPodTarget(), correlation_id="pipeline-failed")
    assert outcome.state == IncidentState.ESCALATED
    assert outcome.attempts == 3
    assert kubernetes.delete_calls == 3
    incident = await session.get(Incident, outcome.incident_id)
    assert incident is not None and incident.state == IncidentState.ESCALATED
    executions = list(
        (
            await session.execute(
                select(ActionExecution).where(ActionExecution.incident_id == outcome.incident_id)
            )
        ).scalars()
    )
    assert [execution.attempt for execution in executions] == [1, 2, 3]
