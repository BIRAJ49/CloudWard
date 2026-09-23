"""Viewer-safe FinOps APIs and worker-only scenario execution."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.config import Settings, get_settings
from app.db.base import utc_now
from app.db.models import (
    ActorType,
    ChaosExecution,
    Environment,
    ExperimentStatus,
    FinOpsRecommendation,
    FinOpsStatus,
)
from app.db.session import get_session
from app.errors import CloudWardError
from app.events import append_stream_event
from app.finops.schemas import AnalysisResult, GitOpsChangeProposal
from app.finops.service import FINOPS_SCENARIOS, FinOpsRecommendationService
from app.github.factory import build_github_app_client
from app.github.schemas import GitHubChangeProposalRequest, GitHubChangeProposalResponse
from app.github.service import GitHubChangeProposalService
from app.rbac import Permission, require_permission

router = APIRouter(tags=["finops"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
Operator = Annotated[Principal, Depends(require_permission(Permission.DEMO_TRIGGER))]


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cluster_id: uuid.UUID | None
    service: str
    environment: Environment
    recommendation_type: str
    status: FinOpsStatus
    current_config: dict[str, Any]
    recommended_config: dict[str, Any]
    evidence: dict[str, Any]
    estimated_savings: dict[str, Any]
    risk_score: int
    confidence: float
    limitations: list[str]
    evidence_window_start: datetime
    evidence_window_end: datetime
    proposal_version: int
    expires_at: datetime
    pr_reference: str | None
    pr_url: str | None
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: AnalysisResult
    recommendation: RecommendationResponse | None


class FinOpsSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_count: int
    open_recommendation_count: int
    recommendations_with_cost_estimate: int
    potential_savings_observed_window: float
    currency: str
    savings_scope: str
    node_efficiency_recommendations: int


class FinOpsPullRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_commit_sha: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    expected_blob_sha: str | None = Field(
        default=None, min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$"
    )


class InternalFinOpsScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: uuid.UUID


class InternalFinOpsScenarioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: uuid.UUID
    status: ExperimentStatus
    outcome: str
    recommendation_id: uuid.UUID | None


class InternalFinOpsFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(min_length=1, max_length=128)


@router.get("/finops/summary", response_model=FinOpsSummaryResponse)
async def finops_summary(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FinOpsSummaryResponse:
    recommendations = list(
        (
            await session.execute(
                select(FinOpsRecommendation).order_by(FinOpsRecommendation.created_at.desc())
            )
        ).scalars()
    )
    open_states = {
        FinOpsStatus.DETECTED,
        FinOpsStatus.ANALYZED,
        FinOpsStatus.RECOMMENDED,
        FinOpsStatus.PR_CREATED,
        FinOpsStatus.APPROVED,
    }
    savings = 0.0
    estimated = 0
    currency = "USD"
    for recommendation in recommendations:
        value = recommendation.estimated_savings.get("value")
        if isinstance(value, int | float) and value >= 0:
            savings += float(value)
            estimated += 1
            currency = str(recommendation.estimated_savings.get("currency", "USD"))
    return FinOpsSummaryResponse(
        recommendation_count=len(recommendations),
        open_recommendation_count=sum(item.status in open_states for item in recommendations),
        recommendations_with_cost_estimate=estimated,
        potential_savings_observed_window=round(savings, 4),
        currency=currency,
        savings_scope="local OpenCost observed windows; not monthly AWS savings",
        node_efficiency_recommendations=sum(
            item.recommendation_type == "NODE_EFFICIENCY" for item in recommendations
        ),
    )


@router.get("/finops/recommendations", response_model=list[RecommendationResponse])
async def list_recommendations(
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: FinOpsStatus | None = None,
    environment: Environment | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FinOpsRecommendation]:
    statement = select(FinOpsRecommendation)
    if status is not None:
        statement = statement.where(FinOpsRecommendation.status == status)
    if environment is not None:
        statement = statement.where(FinOpsRecommendation.environment == environment)
    return list(
        (
            await session.execute(
                statement.order_by(FinOpsRecommendation.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.get("/finops/recommendations/{recommendation_id}", response_model=RecommendationResponse)
async def get_recommendation(
    recommendation_id: uuid.UUID,
    _: Viewer,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FinOpsRecommendation:
    recommendation = await session.get(FinOpsRecommendation, recommendation_id)
    if recommendation is None:
        raise CloudWardError(
            "FINOPS_RECOMMENDATION_NOT_FOUND",
            "FinOps recommendation was not found",
            status_code=404,
        )
    return recommendation


@router.post("/finops/scenarios/{scenario_id}/analyze", response_model=AnalysisResponse)
async def analyze_finops_scenario(
    scenario_id: str,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisResponse:
    analysis, recommendation = await FinOpsRecommendationService(
        session, settings
    ).analyze_scenario(
        scenario_id,
        actor=principal.login,
        actor_type=ActorType.USER,
    )
    await session.commit()
    return AnalysisResponse(
        analysis=analysis,
        recommendation=(
            RecommendationResponse.model_validate(recommendation) if recommendation else None
        ),
    )


@router.post(
    "/finops/recommendations/{recommendation_id}/pr-preview",
    response_model=GitOpsChangeProposal,
)
async def preview_finops_pr(
    recommendation_id: uuid.UUID,
    _: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitOpsChangeProposal:
    service = FinOpsRecommendationService(session, settings)
    recommendation = await service.get_for_update(recommendation_id)
    proposal = service.build_gitops_proposal(recommendation)
    await session.commit()
    return proposal


@router.post(
    "/finops/recommendations/{recommendation_id}/create-pr",
    response_model=GitHubChangeProposalResponse,
)
async def create_finops_pr(
    recommendation_id: uuid.UUID,
    payload: FinOpsPullRequestRequest,
    principal: Operator,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubChangeProposalResponse:
    service = FinOpsRecommendationService(session, settings)
    recommendation = await service.get_for_update(recommendation_id)
    proposal = service.build_gitops_proposal(recommendation)
    github = build_github_app_client(settings)
    source = await github.read_file(
        proposal.repository,
        proposal.path,
        ref=payload.base_commit_sha,
    )
    if source.sha is None:
        raise CloudWardError(
            "FINOPS_GITOPS_BLOB_MISSING",
            "GitHub did not return the current values blob",
            status_code=502,
        )
    if payload.expected_blob_sha is not None and payload.expected_blob_sha != source.sha:
        raise CloudWardError(
            "FINOPS_RECOMMENDATION_STALE",
            "GitOps values blob changed before pull request creation",
            status_code=409,
        )
    proposed_content = service.patch_gitops_values(recommendation, source.content)
    change_request = GitHubChangeProposalRequest(
        repository=proposal.repository,
        path=proposal.path,
        base="main",
        base_commit_sha=payload.base_commit_sha,
        head=proposal.branch_prefix,
        expected_blob_sha=source.sha,
        proposed_content=proposed_content,
        commit_message=f"CloudWard FinOps recommendation {recommendation.id}",
        title=proposal.title,
        reason=str(recommendation.details.get("why", "Deterministic rightsizing analysis")),
        current_state=recommendation.current_config,
        proposed_state=recommendation.recommended_config,
        evidence={
            **recommendation.evidence,
            "evidence_window_start": recommendation.evidence_window_start.isoformat(),
            "evidence_window_end": recommendation.evidence_window_end.isoformat(),
            "estimated_savings": recommendation.estimated_savings,
            "confidence": recommendation.confidence,
            "limitations": recommendation.limitations,
        },
        risk_score=recommendation.risk_score,
        verification_plan=(
            "Observe workload CPU/memory p95, readiness, restarts, latency, and error rate after rollout."
        ),
        rollback_plan="Revert the pull request to restore the previous resource requests.",
        draft=True,
    )
    result = await GitHubChangeProposalService(
        session,
        github,
    ).create_once(
        subject_id=recommendation.id,
        operation="FINOPS_RIGHTSIZING",
        request=change_request,
        correlation_id=f"finops-{recommendation.id}",
    )
    await service.record_pr_created(
        recommendation,
        pr_reference=f"{result.pull_request.repository}#{result.pull_request.number}",
        pr_url=result.pull_request.url,
        actor=principal.login,
    )
    await session.commit()
    return result


@router.post(
    "/internal/finops/scenarios/{scenario_id}/run",
    response_model=InternalFinOpsScenarioResponse,
    include_in_schema=False,
)
async def run_finops_scenario_job(
    scenario_id: str,
    payload: InternalFinOpsScenarioRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> InternalFinOpsScenarioResponse:
    _require_worker(authorization, settings)
    if scenario_id not in FINOPS_SCENARIOS:
        raise CloudWardError(
            "FINOPS_SCENARIO_NOT_FOUND",
            "FinOps scenario is not in the fixed catalog",
            status_code=404,
        )
    execution = await session.get(ChaosExecution, payload.execution_id, with_for_update=True)
    if execution is None or execution.scenario_id != scenario_id:
        raise CloudWardError(
            "EXECUTION_NOT_FOUND", "Matching FinOps execution was not found", status_code=404
        )
    if execution.status == ExperimentStatus.SUCCEEDED:
        recommendation_value = execution.details.get("recommendation_id")
        return InternalFinOpsScenarioResponse(
            execution_id=execution.id,
            status=execution.status,
            outcome=str(execution.details.get("outcome", "RECOMMENDED")),
            recommendation_id=(
                uuid.UUID(recommendation_value) if isinstance(recommendation_value, str) else None
            ),
        )
    if execution.status not in {ExperimentStatus.PENDING, ExperimentStatus.RUNNING}:
        raise CloudWardError(
            "EXECUTION_NOT_ACTIONABLE", "FinOps execution is no longer actionable", status_code=409
        )
    analysis, recommendation = await FinOpsRecommendationService(
        session, settings
    ).analyze_scenario(
        scenario_id,
        actor="finops-worker",
        actor_type=ActorType.SERVICE,
    )
    now = utc_now()
    execution.status = ExperimentStatus.SUCCEEDED
    execution.completed_at = now
    execution.cleanup_completed_at = now
    execution.details = {
        **execution.details,
        "current_step": "ANALYSIS_COMPLETE",
        "outcome": analysis.outcome,
        "reason": analysis.reason,
        "recommendation_id": str(recommendation.id) if recommendation else None,
        "cleanup_verified": True,
    }
    await append_stream_event(
        session,
        event_type="incident_lab.execution",
        incident_id=None,
        payload={
            "execution_id": str(execution.id),
            "scenario_id": scenario_id,
            "status": execution.status.value,
            "current_step": "ANALYSIS_COMPLETE",
            "outcome": analysis.outcome,
            "recommendation_id": str(recommendation.id) if recommendation else None,
        },
    )
    await session.commit()
    return InternalFinOpsScenarioResponse(
        execution_id=execution.id,
        status=execution.status,
        outcome=analysis.outcome,
        recommendation_id=recommendation.id if recommendation else None,
    )


def _require_worker(authorization: str | None, settings: Settings) -> None:
    expected = f"Bearer {settings.worker_internal_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise CloudWardError(
            "WORKER_AUTHENTICATION_FAILED", "Worker authentication failed", status_code=401
        )


@router.post(
    "/internal/finops/executions/{execution_id}/fail",
    response_model=InternalFinOpsScenarioResponse,
    include_in_schema=False,
)
async def fail_finops_scenario_job(
    execution_id: uuid.UUID,
    payload: InternalFinOpsFailureRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> InternalFinOpsScenarioResponse:
    _require_worker(authorization, settings)
    execution = await session.get(ChaosExecution, execution_id, with_for_update=True)
    if execution is None or execution.scenario_id not in FINOPS_SCENARIOS:
        raise CloudWardError(
            "EXECUTION_NOT_FOUND", "FinOps execution was not found", status_code=404
        )
    if execution.status in {ExperimentStatus.PENDING, ExperimentStatus.RUNNING}:
        now = utc_now()
        execution.status = ExperimentStatus.FAILED
        execution.completed_at = now
        execution.cleanup_completed_at = now
        execution.failure_reason = "FinOps providers did not produce a valid bounded analysis"
        execution.details = {
            **execution.details,
            "current_step": "FAILED",
            "error_code": payload.error_code,
            "cleanup_verified": True,
        }
        await append_stream_event(
            session,
            event_type="incident_lab.execution",
            incident_id=None,
            payload={
                "execution_id": str(execution.id),
                "scenario_id": execution.scenario_id,
                "status": execution.status.value,
                "current_step": "FAILED",
                "error_code": payload.error_code,
                "cleanup_verified": True,
            },
        )
        await session.commit()
    return InternalFinOpsScenarioResponse(
        execution_id=execution.id,
        status=execution.status,
        outcome="FAILED",
        recommendation_id=None,
    )
