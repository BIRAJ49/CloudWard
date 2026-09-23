"""Alert-driven reliability workflow using Part 1 risk, OPA, and action registries."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.schemas import NormalizedAlert
from app.audit import record_audit
from app.config import Settings
from app.db.models import (
    ActionProposal,
    ActorType,
    EvidencePhase,
    EvidenceSnapshot,
    Incident,
    PolicyDecision,
    RecordStatus,
    RunbookExecution,
)
from app.errors import CloudWardError
from app.events import append_stream_event
from app.evidence.types import EvidenceType
from app.incidents.service import change_incident_state
from app.incidents.state_machine import IncidentState
from app.kubernetes import KubernetesExecutor
from app.observability import IncidentEvidenceService, TelemetryTarget
from app.policies.opa import OPAClient, PolicyInput, TargetInput
from app.remediation.actions import ActionType, get_action_metadata
from app.remediation.execution import claim_action_execution, finish_action_execution
from app.remediation.gitops import (
    CONTROLLED_BAD_TAG,
    KNOWN_GOOD_TAG,
    LocalGitOpsImageWriter,
)
from app.risk import RiskContext, RiskEngine
from app.runbooks import RunbookLoader

ALERT_CONDITIONS = {
    "HighHTTPErrorRate": {"high_http_error_rate", "recent_deployment"},
    "HighCPUSaturation": {"cpu_saturated", "latency_degraded"},
    "ContainerOOMKilled": {"container_oomkilled", "restart_count_increased"},
    "WorkloadUnavailable": {"workload_disrupted", "controller_reconciled"},
}


class ReliabilityProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: uuid.UUID
    state: IncidentState
    runbook_id: str | None
    action: ActionType | None
    risk_score: int | None
    detail: str


class ReliabilityAlertProcessor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        kubernetes: KubernetesExecutor,
        evidence: IncidentEvidenceService,
        runbooks: RunbookLoader,
        opa: OPAClient,
        settings: Settings,
    ) -> None:
        self.session = session
        self.kubernetes = kubernetes
        self.evidence = evidence
        self.runbooks = runbooks
        self.opa = opa
        self.settings = settings
        self.gitops = LocalGitOpsImageWriter(settings)

    async def process(
        self, *, incident: Incident, alert: NormalizedAlert
    ) -> ReliabilityProcessingResult:
        existing = (
            await self.session.execute(
                select(ActionProposal)
                .where(ActionProposal.incident_id == incident.id)
                .order_by(ActionProposal.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._result(incident, existing.action_type, "alert was already processed")
        if incident.state == IncidentState.DETECTED:
            await change_incident_state(
                self.session,
                incident,
                IncidentState.COLLECTING_EVIDENCE,
                actor="reliability-worker",
                actor_type=ActorType.SERVICE,
            )
        namespace = alert.namespace or "cloudward-staging"
        if namespace != "cloudward-staging":
            raise CloudWardError(
                "RELIABILITY_TARGET_DENIED", "Part 2 remediation is staging-only", status_code=403
            )
        deployment_name = alert.labels.get("deployment", "cloudward-demo")
        label_selector = "cloudward.io/demo-target=true"
        pods = await self.kubernetes.get_pods(namespace, label_selector)
        if not pods:
            raise CloudWardError(
                "RELIABILITY_TARGET_UNAVAILABLE", "No demo target pods were found", status_code=409
            )
        deployment = await self.kubernetes.get_deployment(namespace, deployment_name)
        events = await self.kubernetes.get_events(namespace, deployment_name)
        self.session.add_all(
            [
                EvidenceSnapshot(
                    incident_id=incident.id,
                    correlation_id=incident.correlation_id,
                    evidence_type=EvidenceType.KUBERNETES_STATE,
                    phase=EvidencePhase.INCIDENT,
                    summary="Bounded deployment and pod state",
                    payload={
                        "deployment": deployment.to_dict(),
                        "pods": [pod.to_dict() for pod in pods],
                    },
                    collected_by="reliability-worker",
                ),
                EvidenceSnapshot(
                    incident_id=incident.id,
                    correlation_id=incident.correlation_id,
                    evidence_type=EvidenceType.KUBERNETES_EVENT,
                    phase=EvidencePhase.INCIDENT,
                    summary="Selected Kubernetes events",
                    payload={"events": events[-50:]},
                    collected_by="reliability-worker",
                ),
            ]
        )
        await self.evidence.collect(
            self.session,
            incident_id=incident.id,
            correlation_id=incident.correlation_id,
            target=TelemetryTarget(service=alert.service, namespace=namespace),
            incident_started_at=alert.starts_at,
        )
        await record_audit(
            self.session,
            event_type="EVIDENCE_COLLECTED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
            result="SUCCEEDED",
            metadata={"bounded": True, "providers": ["kubernetes", "prometheus", "loki", "tempo"]},
        )
        await change_incident_state(
            self.session,
            incident,
            IncidentState.CLASSIFYING,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
        )
        conditions = ALERT_CONDITIONS.get(alert.alert_name, {"prometheus_alert"})
        try:
            runbook = self.runbooks.match(
                incident_type=incident.incident_type,
                conditions=conditions,
                environment=incident.environment.value,
            )
        except CloudWardError as exc:
            if exc.code != "RUNBOOK_NOT_FOUND":
                raise
            await record_audit(
                self.session,
                event_type="DETERMINISTIC_RUNBOOK_UNAVAILABLE",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor="reliability-worker",
                actor_type=ActorType.SERVICE,
                result="UNAVAILABLE",
                metadata={
                    "alert_name": alert.alert_name,
                    "conditions": sorted(conditions),
                    "supplemental_diagnosis_candidate": True,
                },
            )
            await append_stream_event(
                self.session,
                event_type="incident.deterministic_diagnosis_unavailable",
                incident_id=incident.id,
                payload={
                    "alert_name": alert.alert_name,
                    "state": incident.state.value,
                    "supplemental_diagnosis_candidate": True,
                },
            )
            return ReliabilityProcessingResult(
                incident_id=incident.id,
                state=incident.state,
                runbook_id=None,
                action=None,
                risk_score=None,
                detail="no deterministic runbook matched; no action was proposed",
            )
        incident.runbook_id = runbook.id
        incident.runbook_version = runbook.version
        self.session.add(
            RunbookExecution(
                incident_id=incident.id,
                runbook_id=runbook.id,
                runbook_version=runbook.version,
                status=RecordStatus.RUNNING,
                context={"alert_name": alert.alert_name, "conditions": sorted(conditions)},
            )
        )
        await record_audit(
            self.session,
            event_type="RUNBOOK_SELECTED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            action=runbook.action.type.value,
            result="SUCCEEDED",
            metadata={"runbook_id": runbook.id, "version": runbook.version},
        )
        await change_incident_state(
            self.session,
            incident,
            IncidentState.ACTION_PROPOSED,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
        )
        action = runbook.action.type
        metadata = get_action_metadata(action)
        risk = RiskEngine.calculate(
            RiskContext(
                environment=incident.environment.value,
                action=action,
                target_count=len(pods),
                reversible=metadata.reversible,
                confidence=0.98,
            )
        )
        incident.risk_score = risk.score
        parameters: dict[str, Any] = {
            "namespace": namespace,
            "deployment": deployment_name,
            "label_selector": label_selector,
            "target_count": len(pods),
            "observed_replicas": deployment.desired_replicas,
        }
        if action == ActionType.REVERT_IMAGE:
            parameters.update(
                {
                    "expected_current_tag": CONTROLLED_BAD_TAG,
                    "target_tag": KNOWN_GOOD_TAG,
                    "values_path": "cloudward-gitops/environments/local/values.yaml",
                    "branch": "main",
                }
            )
        proposal = ActionProposal(
            incident_id=incident.id,
            correlation_id=incident.correlation_id,
            action_type=action,
            parameters=parameters,
            risk_score=risk.score,
            risk_calculation=risk.model_dump(mode="json"),
        )
        self.session.add(proposal)
        await self.session.flush()
        await change_incident_state(
            self.session,
            incident,
            IncidentState.POLICY_EVALUATION,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
        )
        target_pod = pods[0]
        policy_input = PolicyInput(
            environment=incident.environment.value,
            action=action,
            risk_score=risk.score,
            risk_factors=risk.factors,
            confidence=0.98,
            blast_radius=len(pods),
            reversible=metadata.reversible,
            service_criticality="low",
            target=TargetInput(
                namespace=namespace,
                pod_name=target_pod.name,
                labels=target_pod.labels,
                controller_managed=target_pod.controller_managed,
                target_pods=len(pods),
            ),
        )
        policy = await self.opa.evaluate(policy_input)
        self.session.add(
            PolicyDecision(
                incident_id=incident.id,
                proposal_id=proposal.id,
                correlation_id=incident.correlation_id,
                policy_path=self.settings.opa_decision_path,
                allowed=policy.allowed,
                requires_approval=policy.requires_approval,
                reason=policy.reason,
                input_digest=policy_input.digest(),
                result=policy.model_dump(mode="json"),
            )
        )
        await record_audit(
            self.session,
            event_type="OPA_EVALUATED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            action=action.value,
            risk_score=risk.score,
            policy_decision="ALLOW" if policy.allowed else "DENY",
            result="SUCCEEDED",
            metadata={"reason": policy.reason, "requires_approval": policy.requires_approval},
        )
        if not policy.allowed:
            target_state = (
                IncidentState.AWAITING_APPROVAL
                if policy.requires_approval
                else IncidentState.BLOCKED
            )
            await change_incident_state(
                self.session,
                incident,
                target_state,
                actor="reliability-worker",
                actor_type=ActorType.SERVICE,
                details={"policy_reason": policy.reason},
            )
            proposal.status = (
                RecordStatus.PENDING if policy.requires_approval else RecordStatus.REJECTED
            )
            return self._result(incident, action, policy.reason)

        if action == ActionType.REVERT_IMAGE and not self.settings.local_gitops_write_enabled:
            proposal.status = RecordStatus.PENDING
            await change_incident_state(
                self.session,
                incident,
                IncidentState.AWAITING_APPROVAL,
                actor="reliability-worker",
                actor_type=ActorType.SERVICE,
                details={"reason": "typed local GitOps image writer is disabled"},
            )
            return self._result(incident, action, "GitOps revert awaits the enabled local writer")

        proposal.status = RecordStatus.RUNNING
        await change_incident_state(
            self.session,
            incident,
            IncidentState.EXECUTING,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
        )
        if action == ActionType.NO_ACTION:
            proposal.status = RecordStatus.SUCCEEDED
        else:
            claim = await claim_action_execution(
                self.session,
                incident=incident,
                proposal=proposal,
                runbook_id=runbook.id,
                target=parameters,
                attempt=1,
            )
            if claim.claimed:
                if action == ActionType.SCALE_STAGING_DEPLOYMENT:
                    desired = min(
                        deployment.desired_replicas + 1, self.settings.max_temporary_replicas
                    )
                    scale_result = await self.kubernetes.scale_staging_deployment(
                        namespace,
                        deployment_name,
                        replicas=desired,
                        maximum_replicas=self.settings.max_temporary_replicas,
                        expected_current_replicas=deployment.desired_replicas,
                    )
                    await finish_action_execution(
                        self.session,
                        incident=incident,
                        execution=claim.execution,
                        succeeded=True,
                        result=scale_result.to_dict(),
                    )
                elif action == ActionType.DELETE_UNHEALTHY_POD:
                    unhealthy = next((pod for pod in pods if not pod.ready), None)
                    if unhealthy is None:
                        await finish_action_execution(
                            self.session,
                            incident=incident,
                            execution=claim.execution,
                            succeeded=False,
                            result={"recommendation": "review container memory limit and request"},
                            error_code="NO_UNHEALTHY_POD_REMAINED",
                        )
                    else:
                        deletion_result = await self.kubernetes.delete_pod(
                            namespace, unhealthy.name
                        )
                        await finish_action_execution(
                            self.session,
                            incident=incident,
                            execution=claim.execution,
                            succeeded=True,
                            result=deletion_result.to_dict(),
                        )
                elif action == ActionType.REVERT_IMAGE:
                    gitops_result = await self.gitops.revert_to_known_good(incident_id=incident.id)
                    await finish_action_execution(
                        self.session,
                        incident=incident,
                        execution=claim.execution,
                        succeeded=True,
                        result=gitops_result.model_dump(mode="json"),
                    )
            proposal.status = claim.execution.status
        await change_incident_state(
            self.session,
            incident,
            IncidentState.VERIFYING,
            actor="reliability-worker",
            actor_type=ActorType.SERVICE,
            details={"verification": "multi_signal_pending"},
        )
        return self._result(incident, action, "action processed; multi-signal verification queued")

    @staticmethod
    def _result(
        incident: Incident, action: ActionType | None, detail: str
    ) -> ReliabilityProcessingResult:
        return ReliabilityProcessingResult(
            incident_id=incident.id,
            state=incident.state,
            runbook_id=incident.runbook_id,
            action=action,
            risk_score=incident.risk_score,
            detail=detail,
        )
