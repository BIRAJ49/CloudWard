"""End-to-end deterministic unhealthy-pod remediation workflow."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.base import utc_now
from app.db.models import (
    ActionExecution,
    ActionProposal,
    ActorType,
    Environment,
    EvidenceSnapshot,
    Incident,
    PolicyDecision,
    RecordStatus,
    RunbookExecution,
)
from app.errors import CloudWardError
from app.evidence.collector import EvidenceCollector, KubernetesEvidence
from app.evidence.types import EvidenceType
from app.incidents.service import change_incident_state, create_incident
from app.incidents.state_machine import IncidentState
from app.kubernetes.executor import KubernetesExecutor, PodState
from app.policies.opa import OPAClient, PolicyInput, PolicyResult, TargetInput
from app.remediation.actions import ActionType, require_executable_action
from app.risk import RiskContext, RiskEngine, RiskResult
from app.runbooks import RunbookDocument, RunbookLoader
from app.verification import VerificationEngine, VerificationResult


class UnhealthyPodTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(default="cloudward-staging", min_length=1, max_length=253)
    deployment: str = Field(default="cloudward-demo", min_length=1, max_length=253)
    service_name: str = Field(default="cloudward-demo", min_length=1, max_length=253)
    label_selector: str = Field(
        default="app.kubernetes.io/name=cloudward-demo", min_length=1, max_length=512
    )
    pod_name: str | None = Field(default=None, min_length=1, max_length=253)
    expected_replicas: int = Field(default=2, ge=1, le=20)
    environment: Environment = Environment.STAGING
    health_path: str = Field(default="health/ready", min_length=1, max_length=256)


class PipelineOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    incident_id: uuid.UUID
    state: IncidentState
    risk_score: int | None = None
    policy: PolicyResult | None = None
    verification: VerificationResult | None = None
    attempts: int


class UnhealthyPodPipeline:
    """Orchestrates deterministic evidence → policy → typed action → verification."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        kubernetes: KubernetesExecutor,
        runbooks: RunbookLoader,
        opa: OPAClient,
        settings: Settings,
    ) -> None:
        self.session = session
        self.kubernetes = kubernetes
        self.evidence = EvidenceCollector(kubernetes)
        self.verifier = VerificationEngine(kubernetes)
        self.runbooks = runbooks
        self.opa = opa
        self.settings = settings

    async def run(
        self,
        target: UnhealthyPodTarget,
        *,
        correlation_id: str,
        actor: str = "cloudward",
        actor_type: ActorType = ActorType.SYSTEM,
    ) -> PipelineOutcome:
        incident = await create_incident(
            self.session,
            correlation_id=correlation_id,
            incident_type="reliability",
            title="Unhealthy Demo Pod",
            summary="A controlled CloudWard demo pod failed readiness",
            environment=target.environment,
            actor=actor,
            actor_type=actor_type,
        )
        await self.session.commit()
        try:
            return await self._process(incident, target, actor=actor, actor_type=actor_type)
        except CloudWardError as exc:
            await self.session.rollback()
            await self.session.refresh(incident)
            if incident.state not in {
                IncidentState.RESOLVED,
                IncidentState.BLOCKED,
                IncidentState.ESCALATED,
            }:
                await change_incident_state(
                    self.session,
                    incident,
                    IncidentState.ESCALATED,
                    actor=actor,
                    actor_type=actor_type,
                    details={"error_code": exc.code},
                )
                await record_audit(
                    self.session,
                    event_type="INCIDENT_ESCALATED",
                    correlation_id=incident.correlation_id,
                    incident_id=incident.id,
                    actor=actor,
                    actor_type=actor_type,
                    result="FAILED",
                    metadata={"error_code": exc.code, "message": exc.message},
                )
                await self.session.commit()
            return PipelineOutcome(
                incident_id=incident.id,
                state=incident.state,
                risk_score=incident.risk_score,
                attempts=incident.retry_count,
            )

    async def _process(
        self,
        incident: Incident,
        target: UnhealthyPodTarget,
        *,
        actor: str,
        actor_type: ActorType,
    ) -> PipelineOutcome:
        await change_incident_state(
            self.session,
            incident,
            IncidentState.COLLECTING_EVIDENCE,
            actor=actor,
            actor_type=actor_type,
        )
        evidence = await self.evidence.collect_kubernetes_state(
            namespace=target.namespace,
            deployment=target.deployment,
            label_selector=target.label_selector,
        )
        self.session.add(
            EvidenceSnapshot(
                incident_id=incident.id,
                correlation_id=incident.correlation_id,
                evidence_type=EvidenceType.KUBERNETES_STATE,
                summary="Deployment and pod readiness snapshot",
                payload=evidence.to_payload(),
            )
        )
        service_health = await self.kubernetes.get_service_health(
            target.namespace, target.service_name, target.health_path
        )
        self.session.add(
            EvidenceSnapshot(
                incident_id=incident.id,
                correlation_id=incident.correlation_id,
                evidence_type=EvidenceType.HEALTH_CHECK,
                summary="Application health through Kubernetes service proxy",
                payload=service_health.to_dict(),
            )
        )
        await record_audit(
            self.session,
            event_type="EVIDENCE_COLLECTED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            result="SUCCEEDED",
            metadata={
                "evidence_types": [
                    EvidenceType.KUBERNETES_STATE.value,
                    EvidenceType.HEALTH_CHECK.value,
                ],
                "unhealthy_pod_count": len(evidence.unhealthy_pods),
            },
        )
        await self.session.commit()

        unhealthy_pod = self._select_unhealthy_pod(evidence, target.pod_name)
        await change_incident_state(
            self.session,
            incident,
            IncidentState.CLASSIFYING,
            actor=actor,
            actor_type=actor_type,
            details={"classification": "pod_unhealthy"},
        )
        runbook = self.runbooks.match(
            incident_type="reliability",
            conditions={"pod_unhealthy"},
            environment=target.environment.value,
        )
        self._validate_preconditions(runbook, evidence, unhealthy_pod)
        incident.runbook_id = runbook.id
        incident.runbook_version = runbook.version
        runbook_execution = RunbookExecution(
            incident_id=incident.id,
            runbook_id=runbook.id,
            runbook_version=runbook.version,
            status=RecordStatus.RUNNING,
            context={"conditions": ["pod_unhealthy"]},
        )
        self.session.add(runbook_execution)
        await record_audit(
            self.session,
            event_type="RUNBOOK_SELECTED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            action=runbook.action.type.value,
            result="SUCCEEDED",
            metadata={"runbook_id": runbook.id, "runbook_version": runbook.version},
        )
        await change_incident_state(
            self.session,
            incident,
            IncidentState.ACTION_PROPOSED,
            actor=actor,
            actor_type=actor_type,
            details={"runbook_id": runbook.id, "runbook_version": runbook.version},
        )

        action = runbook.action.type
        metadata = require_executable_action(action, target.environment.value)
        risk = RiskEngine.calculate(
            RiskContext(
                environment=target.environment.value,
                action=action,
                target_count=1,
                reversible=metadata.reversible,
                confidence=0.98,
            )
        )
        incident.risk_score = risk.score
        proposal = ActionProposal(
            incident_id=incident.id,
            correlation_id=incident.correlation_id,
            action_type=action,
            parameters=self._proposal_parameters(target, unhealthy_pod),
            risk_score=risk.score,
            risk_calculation=risk.model_dump(mode="json"),
        )
        self.session.add(proposal)
        await self.session.flush()
        await record_audit(
            self.session,
            event_type="ACTION_PROPOSED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            action=action.value,
            risk_score=risk.score,
            result="SUCCEEDED",
            metadata={"proposal_id": str(proposal.id)},
        )
        await record_audit(
            self.session,
            event_type="RISK_CALCULATED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            action=action.value,
            risk_score=risk.score,
            result="SUCCEEDED",
            metadata=risk.model_dump(mode="json"),
        )
        await change_incident_state(
            self.session,
            incident,
            IncidentState.POLICY_EVALUATION,
            actor=actor,
            actor_type=actor_type,
        )
        policy_input = self._policy_input(target, unhealthy_pod, action, risk)
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
            actor=actor,
            actor_type=actor_type,
            action=action.value,
            risk_score=risk.score,
            policy_decision="ALLOW" if policy.allowed else "DENY",
            result="SUCCEEDED",
            metadata={
                "requires_approval": policy.requires_approval,
                "reason": policy.reason,
                "input_digest": policy_input.digest(),
            },
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
                actor=actor,
                actor_type=actor_type,
                details={"policy_reason": policy.reason},
            )
            proposal.status = (
                RecordStatus.PENDING if policy.requires_approval else RecordStatus.REJECTED
            )
            runbook_execution.status = (
                RecordStatus.PENDING if policy.requires_approval else RecordStatus.REJECTED
            )
            if policy.requires_approval:
                await record_audit(
                    self.session,
                    event_type="APPROVAL_REQUESTED",
                    correlation_id=incident.correlation_id,
                    incident_id=incident.id,
                    actor=actor,
                    actor_type=actor_type,
                    action=action.value,
                    risk_score=risk.score,
                    policy_decision="APPROVAL_REQUIRED",
                    result="PENDING",
                    metadata={"proposal_id": str(proposal.id), "reason": policy.reason},
                )
            await self.session.commit()
            return PipelineOutcome(
                incident_id=incident.id,
                state=target_state,
                risk_score=risk.score,
                policy=policy,
                attempts=0,
            )

        proposal.status = RecordStatus.RUNNING
        await change_incident_state(
            self.session,
            incident,
            IncidentState.EXECUTING,
            actor=actor,
            actor_type=actor_type,
        )
        await self.session.commit()
        verification: VerificationResult | None = None
        current_pod: PodState | None = unhealthy_pod
        for attempt in range(1, self.settings.max_remediation_attempts + 1):
            incident.retry_count = attempt
            execution = ActionExecution(
                incident_id=incident.id,
                proposal_id=proposal.id,
                correlation_id=incident.correlation_id,
                action_type=ActionType.DELETE_UNHEALTHY_POD,
                attempt=attempt,
                status=RecordStatus.RUNNING,
            )
            self.session.add(execution)
            await self.session.flush()
            if current_pod is not None:
                deletion = await self.kubernetes.delete_pod(target.namespace, current_pod.name)
                execution.status = RecordStatus.SUCCEEDED
                execution.result = deletion.to_dict()
                execution.completed_at = utc_now()
                await record_audit(
                    self.session,
                    event_type="ACTION_EXECUTED",
                    correlation_id=incident.correlation_id,
                    incident_id=incident.id,
                    actor=actor,
                    actor_type=actor_type,
                    action=action.value,
                    risk_score=risk.score,
                    policy_decision="ALLOW",
                    result="SUCCEEDED",
                    metadata={"attempt": attempt, **deletion.to_dict()},
                )
            else:
                execution.status = RecordStatus.FAILED
                execution.error_code = "NO_UNHEALTHY_TARGET"
                execution.result = {"detail": "No unhealthy pod remained for action retry"}
                execution.completed_at = utc_now()
            await change_incident_state(
                self.session,
                incident,
                IncidentState.VERIFYING,
                actor=actor,
                actor_type=actor_type,
                details={"attempt": attempt},
            )
            await self.session.commit()
            verification = await self.verifier.verify_until(
                namespace=target.namespace,
                deployment=target.deployment,
                label_selector=target.label_selector,
                expected_replicas=target.expected_replicas,
                service_name=target.service_name,
                health_path=target.health_path,
                timeout_seconds=min(
                    runbook.verify.timeout_seconds, self.settings.verification_timeout_seconds
                ),
                poll_seconds=self.settings.verification_poll_seconds,
            )
            self.session.add(
                EvidenceSnapshot(
                    incident_id=incident.id,
                    correlation_id=incident.correlation_id,
                    evidence_type=EvidenceType.HEALTH_CHECK,
                    summary=f"Post-remediation verification attempt {attempt}",
                    payload=verification.model_dump(mode="json"),
                )
            )
            await record_audit(
                self.session,
                event_type="VERIFICATION_COMPLETED",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor=actor,
                actor_type=actor_type,
                action=action.value,
                risk_score=risk.score,
                result="SUCCEEDED" if verification.success else "FAILED",
                metadata={"attempt": attempt, **verification.model_dump(mode="json")},
            )
            if verification.success:
                proposal.status = RecordStatus.SUCCEEDED
                runbook_execution.status = RecordStatus.SUCCEEDED
                await change_incident_state(
                    self.session,
                    incident,
                    IncidentState.RESOLVED,
                    actor=actor,
                    actor_type=actor_type,
                    details={"verification_attempt": attempt},
                )
                await record_audit(
                    self.session,
                    event_type="INCIDENT_RESOLVED",
                    correlation_id=incident.correlation_id,
                    incident_id=incident.id,
                    actor=actor,
                    actor_type=actor_type,
                    result="SUCCEEDED",
                )
                await self.session.commit()
                return PipelineOutcome(
                    incident_id=incident.id,
                    state=IncidentState.RESOLVED,
                    risk_score=risk.score,
                    policy=policy,
                    verification=verification,
                    attempts=attempt,
                )
            if attempt < self.settings.max_remediation_attempts:
                await change_incident_state(
                    self.session,
                    incident,
                    IncidentState.EXECUTING,
                    actor=actor,
                    actor_type=actor_type,
                    details={"retry": attempt + 1},
                )
                refreshed = await self.evidence.collect_kubernetes_state(
                    namespace=target.namespace,
                    deployment=target.deployment,
                    label_selector=target.label_selector,
                )
                unhealthy = refreshed.unhealthy_pods
                current_pod = unhealthy[0] if len(unhealthy) == 1 else None
                if current_pod is not None:
                    retry_input = self._policy_input(target, current_pod, action, risk)
                    retry_policy = await self.opa.evaluate(retry_input)
                    self.session.add(
                        PolicyDecision(
                            incident_id=incident.id,
                            proposal_id=proposal.id,
                            correlation_id=incident.correlation_id,
                            policy_path=self.settings.opa_decision_path,
                            allowed=retry_policy.allowed,
                            requires_approval=retry_policy.requires_approval,
                            reason=retry_policy.reason,
                            input_digest=retry_input.digest(),
                            result=retry_policy.model_dump(mode="json"),
                        )
                    )
                    if not retry_policy.allowed:
                        raise CloudWardError(
                            "RETRY_POLICY_DENIED",
                            "Policy denied the newly discovered retry target",
                            status_code=403,
                        )
                await self.session.commit()
        proposal.status = RecordStatus.FAILED
        runbook_execution.status = RecordStatus.FAILED
        await change_incident_state(
            self.session,
            incident,
            IncidentState.ESCALATED,
            actor=actor,
            actor_type=actor_type,
            details={"reason": "maximum remediation attempts reached"},
        )
        await record_audit(
            self.session,
            event_type="INCIDENT_ESCALATED",
            correlation_id=incident.correlation_id,
            incident_id=incident.id,
            actor=actor,
            actor_type=actor_type,
            result="FAILED",
            metadata={"attempts": self.settings.max_remediation_attempts},
        )
        await self.session.commit()
        return PipelineOutcome(
            incident_id=incident.id,
            state=IncidentState.ESCALATED,
            risk_score=risk.score,
            policy=policy,
            verification=verification,
            attempts=self.settings.max_remediation_attempts,
        )

    @staticmethod
    def _select_unhealthy_pod(evidence: KubernetesEvidence, requested_name: str | None) -> PodState:
        candidates = evidence.unhealthy_pods
        if requested_name is not None:
            candidates = tuple(pod for pod in candidates if pod.name == requested_name)
        if len(candidates) != 1:
            raise CloudWardError(
                "UNSAFE_TARGET_COUNT",
                f"Expected exactly one unhealthy target pod, found {len(candidates)}",
                status_code=409,
            )
        return candidates[0]

    @staticmethod
    def _validate_preconditions(
        runbook: RunbookDocument, evidence: KubernetesEvidence, pod: PodState
    ) -> None:
        if len(evidence.unhealthy_pods) > runbook.preconditions.max_target_pods:
            raise CloudWardError("RUNBOOK_PRECONDITION_FAILED", "Too many target pods")
        if runbook.preconditions.controller_managed and not pod.controller_managed:
            raise CloudWardError("RUNBOOK_PRECONDITION_FAILED", "Target is not controller managed")

    @staticmethod
    def _proposal_parameters(target: UnhealthyPodTarget, pod: PodState) -> dict[str, Any]:
        return {
            "namespace": target.namespace,
            "deployment": target.deployment,
            "service_name": target.service_name,
            "label_selector": target.label_selector,
            "pod_name": pod.name,
            "expected_replicas": target.expected_replicas,
            "labels": pod.labels,
            "controller_managed": pod.controller_managed,
        }

    @staticmethod
    def _policy_input(
        target: UnhealthyPodTarget,
        pod: PodState,
        action: ActionType,
        risk: RiskResult,
    ) -> PolicyInput:
        return PolicyInput(
            environment=target.environment.value,
            action=action,
            risk_score=risk.score,
            risk_factors=risk.factors,
            confidence=0.98,
            blast_radius=1,
            reversible=True,
            service_criticality="low",
            target=TargetInput(
                namespace=target.namespace,
                pod_name=pod.name,
                labels=pod.labels,
                controller_managed=pod.controller_managed,
                target_pods=1,
            ),
        )
