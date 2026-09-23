"""RBAC-enforced Incident Lab APIs backed by the closed scenario catalog."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_chaos_policy_client, get_kubernetes_executor, get_opa_client
from app.audit import record_audit
from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.models import (
    ActionExecution,
    ActorType,
    ChaosExecution,
    ContainmentStatus,
    ExperimentStatus,
    Incident,
    PolicyDecision,
    SecurityEvent,
)
from app.db.session import get_session
from app.demo.executor import ChaosMeshScenarioExecutor
from app.demo.scenarios import SCENARIOS, ChaosScenario, ScenarioMechanism, get_scenario
from app.errors import CloudWardError
from app.events import append_stream_event
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.policies.chaos import ChaosPolicyClient, ChaosPolicyInput
from app.rbac import Permission, require_permission
from app.remediation import RollbackCoordinator, RollbackDisposition
from app.remediation.actions import ActionType
from app.remediation.gitops import LocalGitOpsImageWriter
from app.security.quarantine import remove_quarantine
from app.security.rate_limit import demo_rate_limit

ACTIVE_EXPERIMENT_STATES = {
    ExperimentStatus.PENDING,
    ExperimentStatus.RUNNING,
    ExperimentStatus.STOPPING,
}
MONITOR_TASK = "cloudward.tasks.scenarios.monitor"
FINOPS_TASK = "cloudward.tasks.finops.scenario"


class ScenarioStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scenario_id: str
    status: ExperimentStatus
    requested_by: str
    target_namespace: str
    target_selector: dict[str, str]
    expected_alert: str
    expected_runbook: str
    resource_kind: str | None
    resource_name: str | None
    max_runtime_seconds: int
    cleanup_deadline: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cleanup_completed_at: datetime | None
    failure_reason: str | None
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @computed_field
    def current_step(self) -> str:
        return str(self.details.get("current_step", self.status.value))


router = APIRouter(tags=["incident-lab"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
Operator = Annotated[Principal, Depends(require_permission(Permission.DEMO_TRIGGER))]


@router.get("/scenarios", response_model=list[ChaosScenario])
async def list_scenarios(_: Viewer) -> list[ChaosScenario]:
    return list(SCENARIOS)


@router.post(
    "/scenarios/{scenario_id}/start", response_model=ScenarioExecutionResponse, status_code=202
)
async def start_scenario(
    scenario_id: str,
    _: ScenarioStartRequest,
    principal: Operator,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    chaos_policy: Annotated[ChaosPolicyClient, Depends(get_chaos_policy_client)],
    _rate_limit: Annotated[None, Depends(demo_rate_limit)],
) -> ChaosExecution:
    scenario = get_scenario(scenario_id)
    _enforce_scenario_target(scenario, settings)
    policy = None
    if scenario.mechanism != ScenarioMechanism.FINOPS_ANALYSIS:
        policy = await chaos_policy.evaluate(
            ChaosPolicyInput(
                scenario_id=scenario.id,
                actor_role=principal.role.value,
                namespace=scenario.target_namespace,
                selector=scenario.target_selector,
                duration_seconds=scenario.duration_seconds,
            )
        )
        if not policy.allowed:
            raise CloudWardError("CHAOS_POLICY_DENIED", policy.reason, status_code=403)
    active = (
        await session.execute(
            select(ChaosExecution)
            .where(
                ChaosExecution.scenario_id == scenario.id,
                ChaosExecution.status.in_(ACTIVE_EXPERIMENT_STATES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        raise CloudWardError(
            "SCENARIO_ALREADY_RUNNING",
            "This scenario already has an active execution",
            status_code=409,
        )
    pods = []
    if scenario.mechanism != ScenarioMechanism.FINOPS_ANALYSIS:
        pods = await kubernetes.get_pods(scenario.target_namespace, "cloudward.io/demo-target=true")
        if not pods:
            raise CloudWardError(
                "SCENARIO_TARGET_UNAVAILABLE",
                "No live demo-labeled staging target is available",
                status_code=409,
            )
    now = datetime.now(UTC)
    execution = ChaosExecution(
        scenario_id=scenario.id,
        status=ExperimentStatus.PENDING,
        requested_by=principal.login,
        target_namespace=scenario.target_namespace,
        target_selector=scenario.target_selector,
        expected_alert=scenario.expected_alert,
        expected_runbook=scenario.expected_runbook,
        max_runtime_seconds=min(scenario.max_runtime_seconds, settings.chaos_max_runtime_seconds),
        cleanup_deadline=now
        + timedelta(seconds=min(scenario.max_runtime_seconds, settings.chaos_max_runtime_seconds)),
        details={
            "current_step": "STARTING",
            "cleanup_strategy": scenario.cleanup_strategy,
            "expected_signals": list(scenario.expected_signals),
            "mechanism": scenario.mechanism.value,
            "opa_decision": (
                policy.model_dump(mode="json")
                if policy is not None
                else {
                    "allowed": True,
                    "requires_approval": False,
                    "reason": "Read-only fixed FinOps analysis; no chaos or live mutation",
                }
            ),
        },
    )
    session.add(execution)
    await session.flush()
    if scenario.mechanism in {ScenarioMechanism.STRESS_CHAOS, ScenarioMechanism.POD_CHAOS}:
        resource = await ChaosMeshScenarioExecutor(kubernetes).start(scenario, execution.id)
        execution.resource_kind = resource.kind
        execution.resource_name = resource.name
        execution.status = ExperimentStatus.RUNNING
        execution.started_at = now
        execution.details = {**execution.details, "current_step": "WAITING_FOR_EXPECTED_ALERT"}
    elif scenario.mechanism == ScenarioMechanism.GITOPS_RELEASE:
        gitops = await LocalGitOpsImageWriter(settings).deploy_controlled_bad(
            execution_id=execution.id
        )
        execution.resource_kind = "GitOpsRevision"
        execution.resource_name = gitops.revision
        execution.status = ExperimentStatus.RUNNING
        execution.started_at = now
        execution.details = {
            **execution.details,
            "current_step": "WAITING_FOR_GITOPS_ROLLOUT_AND_ALERT",
            "gitops_trigger": gitops.model_dump(mode="json"),
        }
        await record_audit(
            session,
            event_type="SCENARIO_GITOPS_RELEASE_CREATED",
            correlation_id=str(execution.id),
            actor=principal.login,
            actor_type=ActorType.USER,
            result="SUCCEEDED",
            metadata={
                "execution_id": str(execution.id),
                "scenario_id": scenario.id,
                "revision": gitops.revision,
                "previous_revision": gitops.previous_revision,
                "target_tag": gitops.target_tag,
            },
        )
    elif scenario.mechanism == ScenarioMechanism.SAFE_DEMO_ENDPOINT:
        ready_targets = sorted((pod for pod in pods if pod.ready), key=lambda pod: pod.name)
        if not ready_targets:
            raise CloudWardError(
                "SCENARIO_TARGET_UNAVAILABLE",
                "No ready demo-labeled staging target is available",
                status_code=409,
            )
        target = ready_targets[0]
        trigger = await kubernetes.trigger_controlled_security_scenario(
            scenario.target_namespace,
            target.name,
            scenario.id,
            timeout_seconds=5.0,
        )
        execution.resource_kind = "SafeDemoEndpoint"
        execution.resource_name = target.name
        execution.status = ExperimentStatus.RUNNING
        execution.started_at = now
        execution.details = {
            **execution.details,
            "current_step": "WAITING_FOR_SECURITY_EVENT",
            "triggered_at": now.isoformat(),
            "trigger_timeout_seconds": 5,
            "trigger": trigger.to_dict(),
        }
    elif scenario.mechanism == ScenarioMechanism.FINOPS_ANALYSIS:
        execution.resource_kind = "FinOpsAnalysis"
        execution.resource_name = scenario.id
        execution.status = ExperimentStatus.RUNNING
        execution.started_at = now
        execution.details = {
            **execution.details,
            "current_step": "COLLECTING_OPENCOST_AND_PROMETHEUS",
            "read_only": True,
            "live_mutation": False,
        }
    else:
        execution.details = {**execution.details, "current_step": "QUEUED_FOR_TYPED_WORKER"}
    await append_stream_event(
        session,
        event_type="incident_lab.execution",
        incident_id=None,
        payload={
            "execution_id": str(execution.id),
            "scenario_id": execution.scenario_id,
            "status": execution.status.value,
            "current_step": execution.details.get("current_step"),
        },
    )
    await session.commit()
    task_name = (
        FINOPS_TASK if scenario.mechanism == ScenarioMechanism.FINOPS_ANALYSIS else MONITOR_TASK
    )
    queue = (
        "evidence" if scenario.mechanism == ScenarioMechanism.FINOPS_ANALYSIS else "verification"
    )
    kwargs = (
        {"scenario_id": scenario.id, "execution_id": str(execution.id)}
        if scenario.mechanism == ScenarioMechanism.FINOPS_ANALYSIS
        else {"execution_id": str(execution.id)}
    )
    result = await run_in_threadpool(
        request.app.state.task_publisher.send_task,
        task_name,
        kwargs=kwargs,
        queue=queue,
    )
    execution.details = {**execution.details, "monitor_task_id": str(result.id)}
    await session.commit()
    await session.refresh(execution)
    return execution


@router.get("/executions", response_model=list[ScenarioExecutionResponse])
async def list_executions(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: ExperimentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChaosExecution]:
    statement = select(ChaosExecution)
    if status is not None:
        statement = statement.where(ChaosExecution.status == status)
    return list(
        (
            await session.execute(
                statement.order_by(ChaosExecution.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()
    )


@router.get("/executions/{execution_id}", response_model=ScenarioExecutionResponse)
async def get_execution(
    execution_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChaosExecution:
    execution = await session.get(ChaosExecution, execution_id)
    if execution is None:
        raise CloudWardError(
            "EXECUTION_NOT_FOUND", "Scenario execution was not found", status_code=404
        )
    return execution


@router.post("/executions/{execution_id}/stop", response_model=ScenarioExecutionResponse)
async def stop_execution(
    execution_id: uuid.UUID,
    _: ScenarioStartRequest,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> ChaosExecution:
    execution = await session.get(ChaosExecution, execution_id, with_for_update=True)
    if execution is None:
        raise CloudWardError(
            "EXECUTION_NOT_FOUND", "Scenario execution was not found", status_code=404
        )
    if execution.status not in ACTIVE_EXPERIMENT_STATES:
        return execution
    execution.status = ExperimentStatus.STOPPING
    if execution.resource_kind and execution.resource_name:
        if execution.resource_kind == "FinOpsAnalysis":
            execution.details = {
                **execution.details,
                "finops_cleanup": {"verified": True, "reason": "read-only analysis"},
            }
        elif execution.resource_kind == "GitOpsRevision":
            gitops_cleanup = await LocalGitOpsImageWriter(settings).ensure_known_good(
                execution_id=execution.id
            )
            execution.details = {
                **execution.details,
                "gitops_cleanup": gitops_cleanup.model_dump(mode="json"),
            }
            await record_audit(
                session,
                event_type="SCENARIO_GITOPS_CLEANUP",
                correlation_id=str(execution.id),
                actor=principal.login,
                actor_type=ActorType.USER,
                result="SUCCEEDED",
                metadata={
                    "execution_id": str(execution.id),
                    "revision": gitops_cleanup.revision,
                    "changed": gitops_cleanup.changed,
                },
            )
        else:
            await ChaosMeshScenarioExecutor(kubernetes).cleanup(
                namespace=execution.target_namespace,
                kind=execution.resource_kind,
                name=execution.resource_name,
            )
    cleanup_verified = True
    if execution.scenario_id == "reliability.cpu-saturation":
        scale_cleanup = await _restore_temporary_scale(
            execution,
            session=session,
            settings=settings,
            kubernetes=kubernetes,
        )
        if scale_cleanup is not None:
            execution.details = {**execution.details, "scale_cleanup": scale_cleanup}
    if execution.resource_kind == "SafeDemoEndpoint":
        event_id = execution.details.get("security_event_id")
        event = None
        if isinstance(event_id, str):
            try:
                event = await session.get(SecurityEvent, uuid.UUID(event_id))
            except ValueError:
                event = None
        if event is not None and event.containment_status not in {
            ContainmentStatus.NOT_PROPOSED,
            ContainmentStatus.PROPOSED,
            ContainmentStatus.AWAITING_APPROVAL,
            ContainmentStatus.REMOVED,
        }:
            record = await remove_quarantine(
                session,
                event_id=event.id,
                actor=principal.login,
                settings=settings,
                opa=opa,
                kubernetes=kubernetes,
            )
            cleanup_verified = record.status == ContainmentStatus.REMOVED and bool(
                record.verification.get("success")
            )
            if not cleanup_verified:
                raise CloudWardError(
                    "SCENARIO_CLEANUP_FAILED",
                    "Security scenario containment cleanup could not be verified",
                    status_code=502,
                )
    now = datetime.now(UTC)
    execution.status = ExperimentStatus.CANCELLED
    execution.completed_at = now
    execution.cleanup_completed_at = now
    execution.details = {
        **execution.details,
        "current_step": "CANCELLED",
        "stopped_by": principal.login,
        "cleanup_verified": cleanup_verified,
    }
    await append_stream_event(
        session,
        event_type="incident_lab.execution",
        incident_id=None,
        payload={
            "execution_id": str(execution.id),
            "scenario_id": execution.scenario_id,
            "status": execution.status.value,
            "current_step": "CANCELLED",
            "cleanup_verified": cleanup_verified,
        },
    )
    await session.commit()
    await session.refresh(execution)
    return execution


async def _restore_temporary_scale(
    execution: ChaosExecution,
    *,
    session: AsyncSession,
    settings: Settings,
    kubernetes: KubernetesExecutor,
) -> dict[str, Any] | None:
    incident_value = execution.details.get("incident_id")
    if not isinstance(incident_value, str):
        return None
    try:
        incident_id = uuid.UUID(incident_value)
    except ValueError:
        return None
    incident = await session.get(Incident, incident_id)
    if incident is None:
        return None
    scale_execution = (
        await session.execute(
            select(ActionExecution)
            .where(
                ActionExecution.incident_id == incident.id,
                ActionExecution.action_type == ActionType.SCALE_STAGING_DEPLOYMENT,
                ActionExecution.rollback_of_execution_id.is_(None),
            )
            .order_by(ActionExecution.attempt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        scale_execution is None
        or scale_execution.status.value != "SUCCEEDED"
        or scale_execution.rolled_back_at is not None
    ):
        return None
    latest_policy = (
        await session.execute(
            select(PolicyDecision)
            .where(PolicyDecision.incident_id == incident.id)
            .order_by(PolicyDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    rollback = RollbackCoordinator(automatic_max_risk=settings.automatic_rollback_max_risk)
    disposition = rollback.decide(
        action=scale_execution.action_type,
        risk_score=incident.risk_score if incident.risk_score is not None else 100,
        rollback_enabled=True,
        policy_allows_rollback=bool(latest_policy and latest_policy.allowed),
    )
    if disposition != RollbackDisposition.AUTOMATIC:
        raise CloudWardError(
            "SCENARIO_SCALE_CLEANUP_DENIED",
            "Temporary scale cleanup was not authorized",
            status_code=409,
        )
    rollback_execution = await rollback.rollback_scale(
        session,
        incident=incident,
        failed_execution=scale_execution,
        kubernetes=kubernetes,
        maximum_replicas=settings.max_temporary_replicas,
    )
    restored = int(rollback_execution.result["requested_replicas"])
    deployment_name = str(rollback_execution.result["deployment"])
    namespace = str(rollback_execution.result["namespace"])
    deployment = await kubernetes.get_deployment(namespace, deployment_name)
    if deployment.desired_replicas != restored:
        raise CloudWardError(
            "SCENARIO_SCALE_CLEANUP_FAILED",
            "Temporary replica count was not restored",
            status_code=502,
        )
    return {
        "rollback_execution_id": str(rollback_execution.id),
        "restored_replicas": restored,
        "verified": True,
    }


def _enforce_scenario_target(scenario: ChaosScenario, settings: Settings) -> None:
    if scenario.target_namespace in settings.denied_chaos_namespaces:
        raise CloudWardError(
            "CHAOS_TARGET_DENIED", "Protected namespace cannot be targeted", status_code=403
        )
    if scenario.target_namespace != settings.incident_lab_namespace:
        raise CloudWardError(
            "CHAOS_TARGET_DENIED", "Only cloudward-staging may be targeted", status_code=403
        )
    if scenario.target_selector != {"cloudward.io/demo-target": "true"}:
        raise CloudWardError(
            "CHAOS_TARGET_DENIED", "Demo target label is required", status_code=403
        )
