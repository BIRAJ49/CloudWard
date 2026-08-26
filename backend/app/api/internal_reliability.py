"""Worker callbacks for idempotent alert processing and scenario reconciliation."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.alerts.schemas import NormalizedAlert
from app.ai.models import AIDiagnosisRecord
from app.api.dependencies import get_kubernetes_executor, get_opa_client, get_runbook_loader
from app.audit import record_audit
from app.config import Settings, get_settings
from app.db.models import (
    ActionExecution,
    AlertRecord,
    ChaosExecution,
    ContainmentStatus,
    ExperimentStatus,
    Incident,
    PolicyDecision,
    ResolutionSource,
    SecurityCategory,
    SecurityEvent,
    VerificationRecord,
)
from app.db.session import get_session
from app.demo.executor import ChaosMeshScenarioExecutor
from app.errors import CloudWardError
from app.events import append_stream_event
from app.github.factory import build_github_app_client
from app.github.service import (
    IncidentSourceCorrelationService,
    source_request_from_metadata,
)
from app.incident_memory.fingerprint import (
    DEFAULT_STABLE_LABELS,
    FingerprintInput,
)
from app.incident_memory.service import IncidentMemoryService
from app.kubernetes import KubernetesExecutor
from app.observability import (
    IncidentEvidenceService,
    LokiLogsProvider,
    PrometheusMetricsProvider,
    TempoTracesProvider,
)
from app.policies import OPAClient
from app.security.quarantine import apply_quarantine, remove_quarantine
from app.reliability import ReliabilityAlertProcessor, ReliabilityProcessingResult
from app.reliability.workflow import ALERT_CONDITIONS
from app.remediation import RollbackCoordinator, RollbackDisposition
from app.remediation.actions import ActionType
from app.remediation.gitops import LocalGitOpsImageWriter
from app.runbooks import RunbookLoader
from app.tasks import AI_DIAGNOSIS_QUEUE, AI_DIAGNOSIS_TASK
from app.verification import MultiSignalVerificationEngine, VerificationPlan, persist_verification

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


class AlertJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    alert: NormalizedAlert
    correlation_id: str


class ReconcileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terminal: bool
    status: ExperimentStatus
    retry_after_seconds: int = 5
    detail: str


def _require_worker(authorization: str | None, settings: Settings) -> None:
    expected = f"Bearer {settings.worker_internal_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise CloudWardError("WORKER_AUTHENTICATION_FAILED", "Worker authentication failed", status_code=401)


@router.post("/reliability/process-alert", response_model=ReliabilityProcessingResult)
async def process_alert_job(
    payload: AlertJobRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    runbooks: Annotated[RunbookLoader, Depends(get_runbook_loader)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ReliabilityProcessingResult:
    _require_worker(authorization, settings)
    incident = await session.get(Incident, payload.incident_id)
    if incident is None:
        raise CloudWardError("INCIDENT_NOT_FOUND", "Incident was not found", status_code=404)
    metrics = PrometheusMetricsProvider(
        str(settings.prometheus_url),
        timeout_seconds=settings.telemetry_timeout_seconds,
        max_samples=settings.telemetry_max_samples,
    )
    evidence = IncidentEvidenceService(
        metrics=metrics,
        logs=LokiLogsProvider(
            str(settings.loki_url),
            timeout_seconds=settings.telemetry_timeout_seconds,
            max_samples=settings.telemetry_max_samples,
        ),
        traces=TempoTracesProvider(
            str(settings.tempo_url),
            timeout_seconds=settings.telemetry_timeout_seconds,
            max_samples=settings.telemetry_max_samples,
        ),
        before_seconds=settings.evidence_before_seconds,
    )
    result = await ReliabilityAlertProcessor(
        session=session,
        kubernetes=kubernetes,
        evidence=evidence,
        runbooks=runbooks,
        opa=opa,
        settings=settings,
    ).process(incident=incident, alert=payload.alert)
    await session.commit()
    await _collect_source_correlation(
        session,
        settings=settings,
        incident=incident,
        alert=payload.alert,
    )
    supplemental_reason: str | None = None
    if settings.ai_diagnosis_enabled:
        try:
            supplemental_reason = await _supplemental_ai_reason(
                session,
                incident=incident,
                alert=payload.alert,
                result=result,
            )
        except Exception as exc:
            await session.rollback()
            try:
                await record_audit(
                    session,
                    event_type="AI_DIAGNOSIS_ELIGIBILITY_FAILED",
                    correlation_id=incident.correlation_id,
                    incident_id=incident.id,
                    actor="reliability-worker",
                    result="UNAVAILABLE",
                    metadata={"error_type": type(exc).__name__},
                )
                await session.commit()
            except Exception:
                await session.rollback()
            supplemental_reason = None
    if supplemental_reason is not None:
        try:
            task = await run_in_threadpool(
                request.app.state.task_publisher.send_task,
                AI_DIAGNOSIS_TASK,
                kwargs={"incident_id": str(incident.id)},
                queue=AI_DIAGNOSIS_QUEUE,
            )
        except Exception as exc:
            await record_audit(
                session,
                event_type="AI_DIAGNOSIS_SCHEDULING_FAILED",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor="reliability-worker",
                result="FAILED",
                metadata={
                    "error_type": type(exc).__name__,
                    "supplemental_reason": supplemental_reason,
                },
            )
        else:
            await append_stream_event(
                session,
                event_type="incident.ai_diagnosis_queued",
                incident_id=incident.id,
                payload={
                    "task_id": str(task.id),
                    "advisory_only": True,
                    "supplemental_reason": supplemental_reason,
                },
            )
            await record_audit(
                session,
                event_type="AI_DIAGNOSIS_QUEUED",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor="reliability-worker",
                result="QUEUED",
                metadata={
                    "task_id": str(task.id),
                    "queue": AI_DIAGNOSIS_QUEUE,
                    "supplemental_reason": supplemental_reason,
                },
            )
        await session.commit()
    return result


async def _collect_source_correlation(
    session: AsyncSession,
    *,
    settings: Settings,
    incident: Incident,
    alert: NormalizedAlert,
) -> None:
    try:
        source_request = source_request_from_metadata(alert.labels, alert.annotations)
        if source_request is None:
            return
        await IncidentSourceCorrelationService(
            session,
            build_github_app_client(settings),
        ).correlate_and_store(
            incident=incident,
            request=source_request,
            actor="reliability-worker",
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        error_code = exc.code if isinstance(exc, CloudWardError) else type(exc).__name__
        try:
            await record_audit(
                session,
                event_type="GIT_EVIDENCE_UNAVAILABLE",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor="reliability-worker",
                result="UNAVAILABLE",
                metadata={"error_code": error_code, "remediation_continued": True},
            )
            await append_stream_event(
                session,
                event_type="incident.source_correlation_unavailable",
                incident_id=incident.id,
                payload={"error_code": error_code, "remediation_continued": True},
            )
            await session.commit()
        except Exception:
            await session.rollback()


async def _supplemental_ai_reason(
    session: AsyncSession,
    *,
    incident: Incident,
    alert: NormalizedAlert,
    result: ReliabilityProcessingResult,
) -> str | None:
    existing = (
        await session.execute(
            select(AIDiagnosisRecord.id)
            .where(AIDiagnosisRecord.incident_id == incident.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    if result.runbook_id is None or result.action is None:
        return "no_deterministic_runbook"
    if alert.alert_name not in ALERT_CONDITIONS:
        return "unknown_alert"
    if _alert_marks_uncertainty(alert):
        return "deterministic_diagnosis_uncertain"
    stable_labels = {
        key: value for key, value in alert.labels.items() if key in DEFAULT_STABLE_LABELS
    }
    similar = await IncidentMemoryService(session).find_similar(
        FingerprintInput(
            service=alert.service,
            incident_type=incident.incident_type,
            alert_name=alert.alert_name,
            namespace=alert.namespace,
            labels=stable_labels,
        ),
        exclude_incident_id=incident.id,
        limit=5,
    )
    if not similar:
        return "no_similar_incident_memory"
    if not any(item.successful for item in similar):
        return "no_verified_successful_memory"
    return None


def _alert_marks_uncertainty(alert: NormalizedAlert) -> bool:
    values = {**alert.annotations, **alert.labels}
    explicit = values.get("cloudward.io/diagnosis-uncertain", "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    raw_confidence = values.get("cloudward.io/deterministic-confidence")
    if raw_confidence is None:
        return False
    try:
        return float(raw_confidence) < 0.8
    except ValueError:
        return True


@router.post("/executions/{execution_id}/reconcile", response_model=ReconcileResult)
async def reconcile_execution(
    execution_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
    opa: Annotated[OPAClient, Depends(get_opa_client)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ReconcileResult:
    _require_worker(authorization, settings)
    execution = await session.get(ChaosExecution, execution_id, with_for_update=True)
    if execution is None:
        raise CloudWardError("EXECUTION_NOT_FOUND", "Scenario execution was not found", status_code=404)
    if execution.status not in {
        ExperimentStatus.PENDING,
        ExperimentStatus.RUNNING,
        ExperimentStatus.STOPPING,
    }:
        return ReconcileResult(
            terminal=True, status=execution.status, detail="execution is already terminal"
        )
    now = datetime.now(UTC)
    security_category = {
        "security.suspicious-shell-pattern": SecurityCategory.SUSPICIOUS_PROCESS,
        "security.unexpected-egress": SecurityCategory.UNEXPECTED_EGRESS,
        "security.privilege-related-behavior": SecurityCategory.PRIVILEGE_BEHAVIOR,
    }.get(execution.scenario_id)
    if security_category is not None:
        return await _reconcile_security_execution(
            execution,
            category=security_category,
            now=now,
            session=session,
            settings=settings,
            kubernetes=kubernetes,
            opa=opa,
        )
    if now >= execution.cleanup_deadline:
        await _cleanup(execution, kubernetes, settings, session)
        execution.status = ExperimentStatus.TIMED_OUT
        execution.completed_at = now
        execution.cleanup_completed_at = now
        execution.failure_reason = "expected verified incident lifecycle did not finish before deadline"
        execution.details = {**execution.details, "current_step": "TIMED_OUT"}
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(
            terminal=True, status=execution.status, detail=execution.failure_reason
        )
    alert = (
        await session.execute(
            select(AlertRecord)
            .where(
                AlertRecord.alert_name == execution.expected_alert,
                AlertRecord.last_received_at >= execution.created_at,
            )
            .order_by(AlertRecord.last_received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if alert is None or alert.incident_id is None:
        return ReconcileResult(
            terminal=False,
            status=execution.status,
            detail="waiting for the expected authenticated alert",
        )
    incident = await session.get(Incident, alert.incident_id)
    if incident is None:
        return ReconcileResult(
            terminal=False, status=execution.status, detail="waiting for correlated incident"
        )
    execution.details = {
        **execution.details,
        "incident_id": str(incident.id),
        "current_step": f"INCIDENT_{incident.state.value}",
    }
    if incident.state.value == "VERIFYING":
        deployment_name = alert.labels.get("deployment", "cloudward-demo")
        deployment = await kubernetes.get_deployment(execution.target_namespace, deployment_name)
        if execution.scenario_id == "reliability.bad-deployment" and not any(
            image.endswith(":local") for image in deployment.container_images
        ):
            execution.details = {
                **execution.details,
                "current_step": "WAITING_FOR_ARGO_KNOWN_GOOD_REVISION",
                "observed_images": list(deployment.container_images),
            }
            await _stream_execution(session, execution)
            await session.commit()
            return ReconcileResult(
                terminal=False,
                status=execution.status,
                retry_after_seconds=10,
                detail="waiting for Argo CD to roll out the known-good image",
            )
        verification_count = int(
            (
                await session.execute(
                    select(func.count(VerificationRecord.id)).where(
                        VerificationRecord.incident_id == incident.id
                    )
                )
            ).scalar_one()
        )
        if execution.scenario_id == "reliability.bad-deployment" and verification_count > 0:
            last_completed = (
                await session.execute(
                    select(func.max(VerificationRecord.completed_at)).where(
                        VerificationRecord.incident_id == incident.id
                    )
                )
            ).scalar_one_or_none()
            if last_completed is not None and now < last_completed + timedelta(seconds=60):
                return ReconcileResult(
                    terminal=False,
                    status=execution.status,
                    retry_after_seconds=10,
                    detail="waiting for the bounded post-remediation metric window",
                )
        if verification_count < 3:
            metrics = PrometheusMetricsProvider(
                str(settings.prometheus_url),
                timeout_seconds=settings.telemetry_timeout_seconds,
                max_samples=settings.telemetry_max_samples,
            )
            verification = await MultiSignalVerificationEngine(
                kubernetes=kubernetes, metrics=metrics
            ).verify(
                VerificationPlan(
                    namespace=execution.target_namespace,
                    deployment=deployment_name,
                    label_selector="cloudward.io/demo-target=true",
                    service_name=alert.service,
                    expected_replicas=deployment.desired_replicas,
                ),
                before_values={
                    "ready_replicas": None,
                    "error_rate": None,
                    "p95_latency": None,
                    "source": "bounded incident evidence snapshots",
                },
            )
            action_execution = (
                await session.execute(
                    select(ActionExecution)
                    .where(ActionExecution.incident_id == incident.id)
                    .order_by(ActionExecution.attempt.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            source = (
                ResolutionSource.PLATFORM_SELF_HEALING
                if execution.scenario_id == "reliability.platform-self-healing"
                or action_execution is None
                or action_execution.status.value != "SUCCEEDED"
                else ResolutionSource.CLOUDWARD_REMEDIATION
            )
            await persist_verification(
                session,
                incident=incident,
                result=verification,
                attempt=verification_count + 1,
                action_execution_id=action_execution.id if action_execution else None,
                resolution_source=source,
            )
            if (
                not verification.success
                and action_execution is not None
                and action_execution.action_type == ActionType.SCALE_STAGING_DEPLOYMENT
                and action_execution.rollback_of_execution_id is None
                and action_execution.rolled_back_at is None
            ):
                latest_policy = (
                    await session.execute(
                        select(PolicyDecision)
                        .where(PolicyDecision.incident_id == incident.id)
                        .order_by(PolicyDecision.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                rollback = RollbackCoordinator(
                    automatic_max_risk=settings.automatic_rollback_max_risk
                )
                disposition = rollback.decide(
                    action=action_execution.action_type,
                    risk_score=(
                        incident.risk_score if incident.risk_score is not None else 100
                    ),
                    rollback_enabled=True,
                    policy_allows_rollback=bool(latest_policy and latest_policy.allowed),
                )
                if disposition == RollbackDisposition.AUTOMATIC:
                    await rollback.rollback_scale(
                        session,
                        incident=incident,
                        failed_execution=action_execution,
                        kubernetes=kubernetes,
                        maximum_replicas=settings.max_temporary_replicas,
                    )
    if incident.state.value == "RESOLVED":
        await _cleanup(execution, kubernetes, settings, session)
        execution.status = ExperimentStatus.SUCCEEDED
        execution.completed_at = now
        execution.cleanup_completed_at = now
        execution.details = {**execution.details, "current_step": "COMPLETED"}
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(terminal=True, status=execution.status, detail="incident verified")
    if incident.state.value in {"BLOCKED", "ESCALATED"}:
        await _cleanup(execution, kubernetes, settings, session)
        execution.status = ExperimentStatus.FAILED
        execution.completed_at = now
        execution.cleanup_completed_at = now
        execution.failure_reason = f"incident ended in {incident.state.value}"
        execution.details = {**execution.details, "current_step": "FAILED"}
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(terminal=True, status=execution.status, detail=execution.failure_reason)
    await _stream_execution(session, execution)
    await session.commit()
    return ReconcileResult(
        terminal=False, status=execution.status, detail="incident workflow is still active"
    )


async def _cleanup(
    execution: ChaosExecution,
    kubernetes: KubernetesExecutor,
    settings: Settings,
    session: AsyncSession,
) -> None:
    if execution.resource_kind and execution.resource_name:
        if execution.resource_kind == "GitOpsRevision":
            result = await LocalGitOpsImageWriter(settings).ensure_known_good(
                execution_id=execution.id
            )
            execution.details = {
                **execution.details,
                "gitops_cleanup": result.model_dump(mode="json"),
            }
            await record_audit(
                session,
                event_type="SCENARIO_GITOPS_CLEANUP",
                correlation_id=str(execution.id),
                actor="incident-lab-worker",
                result="SUCCEEDED",
                metadata={
                    "execution_id": str(execution.id),
                    "revision": result.revision,
                    "changed": result.changed,
                },
            )
        else:
            await ChaosMeshScenarioExecutor(kubernetes).cleanup(
                namespace=execution.target_namespace,
                kind=execution.resource_kind,
                name=execution.resource_name,
            )
    if execution.scenario_id == "reliability.cpu-saturation":
        incident_value = execution.details.get("incident_id")
        if isinstance(incident_value, str):
            try:
                incident_id = uuid.UUID(incident_value)
            except ValueError:
                incident_id = None
            incident = await session.get(Incident, incident_id) if incident_id else None
            if incident is not None:
                scale_execution = (
                    await session.execute(
                        select(ActionExecution)
                        .where(
                            ActionExecution.incident_id == incident.id,
                            ActionExecution.action_type
                            == ActionType.SCALE_STAGING_DEPLOYMENT,
                            ActionExecution.rollback_of_execution_id.is_(None),
                        )
                        .order_by(ActionExecution.attempt.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if (
                    scale_execution is not None
                    and scale_execution.status.value == "SUCCEEDED"
                    and scale_execution.rolled_back_at is None
                ):
                    latest_policy = (
                        await session.execute(
                            select(PolicyDecision)
                            .where(PolicyDecision.incident_id == incident.id)
                            .order_by(PolicyDecision.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    rollback = RollbackCoordinator(
                        automatic_max_risk=settings.automatic_rollback_max_risk
                    )
                    disposition = rollback.decide(
                        action=scale_execution.action_type,
                        risk_score=(
                            incident.risk_score if incident.risk_score is not None else 100
                        ),
                        rollback_enabled=True,
                        policy_allows_rollback=bool(
                            latest_policy and latest_policy.allowed
                        ),
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
                    deployment = await kubernetes.get_deployment(
                        execution.target_namespace, deployment_name
                    )
                    if deployment.desired_replicas != restored:
                        raise CloudWardError(
                            "SCENARIO_SCALE_CLEANUP_FAILED",
                            "Temporary replica count was not restored",
                            status_code=502,
                        )
                    execution.details = {
                        **execution.details,
                        "scale_cleanup": {
                            "rollback_execution_id": str(rollback_execution.id),
                            "restored_replicas": restored,
                            "verified": True,
                        },
                    }


async def _reconcile_security_execution(
    execution: ChaosExecution,
    *,
    category: SecurityCategory,
    now: datetime,
    session: AsyncSession,
    settings: Settings,
    kubernetes: KubernetesExecutor,
    opa: OPAClient,
) -> ReconcileResult:
    event_statement = select(SecurityEvent).where(
        SecurityEvent.event_type == category,
        SecurityEvent.namespace == execution.target_namespace,
        SecurityEvent.created_at >= execution.created_at,
    )
    if execution.resource_name:
        event_statement = event_statement.where(SecurityEvent.pod == execution.resource_name)
    event = (
        await session.execute(
            event_statement.order_by(SecurityEvent.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if event is None:
        if now >= execution.cleanup_deadline:
            execution.status = ExperimentStatus.TIMED_OUT
            execution.completed_at = now
            execution.cleanup_completed_at = now
            execution.failure_reason = "expected normalized Tetragon event did not arrive before deadline"
            execution.details = {**execution.details, "current_step": "TIMED_OUT"}
            await _stream_execution(session, execution)
            await session.commit()
            return ReconcileResult(
                terminal=True, status=execution.status, detail=execution.failure_reason
            )
        return ReconcileResult(
            terminal=False,
            status=execution.status,
            detail="waiting for the expected normalized Tetragon event",
        )
    execution.details = {
        **execution.details,
        "security_event_id": str(event.id),
        "incident_id": str(event.incident_id) if event.incident_id else None,
        "containment_status": event.containment_status.value,
        "current_step": f"SECURITY_{event.containment_status.value}",
    }
    incident = await session.get(Incident, event.incident_id) if event.incident_id else None
    if now >= execution.cleanup_deadline:
        cleanup = await _remove_security_containment(
            event, session=session, settings=settings, kubernetes=kubernetes, opa=opa
        )
        execution.status = ExperimentStatus.TIMED_OUT
        execution.completed_at = now
        execution.cleanup_completed_at = now if cleanup else None
        execution.failure_reason = "security scenario did not complete before its bounded deadline"
        execution.details = {
            **execution.details,
            "current_step": "TIMED_OUT",
            "cleanup_verified": cleanup,
        }
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(
            terminal=True, status=execution.status, detail=execution.failure_reason
        )
    if event.containment_status in {
        ContainmentStatus.PROPOSED,
        ContainmentStatus.AWAITING_APPROVAL,
    }:
        record = await apply_quarantine(
            session,
            event_id=event.id,
            actor="incident-lab-worker",
            settings=settings,
            opa=opa,
            kubernetes=kubernetes,
        )
        execution.details = {
            **execution.details,
            "current_step": "CONTAINMENT_VERIFIED",
            "containment_status": record.status.value,
            "quarantine_id": str(record.id),
            "containment_verification": record.verification,
        }
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(
            terminal=False,
            status=execution.status,
            detail="targeted containment verified; cleanup scheduled",
        )
    if event.containment_status == ContainmentStatus.CONTAINED:
        record = await remove_quarantine(
            session,
            event_id=event.id,
            actor="incident-lab-worker",
            settings=settings,
            opa=opa,
            kubernetes=kubernetes,
        )
        execution.details = {
            **execution.details,
            "current_step": "CLEANUP_VERIFIED",
            "containment_status": record.status.value,
            "cleanup_verification": record.verification,
        }
        await session.refresh(event)
        if incident is not None:
            await session.refresh(incident)
    if (
        event.containment_status == ContainmentStatus.REMOVED
        and incident is not None
        and incident.state.value == "RESOLVED"
    ):
        execution.status = ExperimentStatus.SUCCEEDED
        execution.completed_at = now
        execution.cleanup_completed_at = now
        execution.details = {
            **execution.details,
            "current_step": "COMPLETED",
            "cleanup_verified": True,
        }
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(
            terminal=True,
            status=execution.status,
            detail="security incident contained, verified, and cleaned up",
        )
    if (
        event.containment_status == ContainmentStatus.VERIFICATION_FAILED
        or (incident is not None and incident.state.value in {"BLOCKED", "ESCALATED"})
    ):
        cleanup = await _remove_security_containment(
            event, session=session, settings=settings, kubernetes=kubernetes, opa=opa
        )
        execution.status = ExperimentStatus.FAILED
        execution.completed_at = now
        execution.cleanup_completed_at = now if cleanup else None
        execution.failure_reason = "security incident containment or policy verification failed"
        execution.details = {
            **execution.details,
            "current_step": "FAILED",
            "cleanup_verified": cleanup,
        }
        await _stream_execution(session, execution)
        await session.commit()
        return ReconcileResult(
            terminal=True, status=execution.status, detail=execution.failure_reason
        )
    await _stream_execution(session, execution)
    await session.commit()
    return ReconcileResult(
        terminal=False,
        status=execution.status,
        detail="security incident workflow is still active",
    )


async def _stream_execution(session: AsyncSession, execution: ChaosExecution) -> None:
    await append_stream_event(
        session,
        event_type="incident_lab.execution",
        incident_id=None,
        payload={
            "execution_id": str(execution.id),
            "scenario_id": execution.scenario_id,
            "status": execution.status.value,
            "current_step": execution.details.get("current_step"),
            "incident_id": execution.details.get("incident_id"),
            "cleanup_verified": execution.details.get("cleanup_verified"),
        },
    )


async def _remove_security_containment(
    event: SecurityEvent,
    *,
    session: AsyncSession,
    settings: Settings,
    kubernetes: KubernetesExecutor,
    opa: OPAClient,
) -> bool:
    if event.containment_status in {
        ContainmentStatus.NOT_PROPOSED,
        ContainmentStatus.PROPOSED,
        ContainmentStatus.AWAITING_APPROVAL,
        ContainmentStatus.REMOVED,
    }:
        return event.containment_status == ContainmentStatus.REMOVED or event.containment_status in {
            ContainmentStatus.NOT_PROPOSED,
            ContainmentStatus.PROPOSED,
            ContainmentStatus.AWAITING_APPROVAL,
        }
    try:
        record = await remove_quarantine(
            session,
            event_id=event.id,
            actor="incident-lab-worker",
            settings=settings,
            opa=opa,
            kubernetes=kubernetes,
        )
    except CloudWardError:
        return False
    return record.status == ContainmentStatus.REMOVED and bool(
        record.verification.get("success")
    )
