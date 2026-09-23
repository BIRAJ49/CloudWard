"""Operational action catalog and evaluation endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_opa_client
from app.api.schemas import ActionCatalogItem, ActionEvaluationRequest
from app.auth.schemas import Principal
from app.policies.opa import OPAClient, PolicyInput, TargetInput
from app.rbac import Permission, require_permission
from app.remediation.actions import (
    ACTION_REGISTRY,
    get_action_metadata,
)
from app.risk.engine import RiskContext, RiskEngine

router = APIRouter(prefix="/actions", tags=["actions"])

Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]
Operator = Annotated[Principal, Depends(require_permission(Permission.INCIDENT_CREATE))]


@router.get(
    "", response_model=list[ActionCatalogItem], summary="List registered operational actions"
)
async def list_actions(_: Viewer) -> list[ActionCatalogItem]:
    """Return all strongly typed actions in the CloudWard action catalog."""
    return [
        ActionCatalogItem(
            action_type=meta.action_type.value,
            reversible=meta.reversible,
            persistent=meta.persistent,
            allowed_environments=sorted(meta.allowed_environments),
            required_permission=meta.required_permission.value,
            verification_strategy=meta.verification_strategy.value,
            rollback_capable=meta.rollback_capable,
            implemented=meta.implemented,
        )
        for meta in ACTION_REGISTRY.values()
    ]


@router.get(
    "/{action_type}", response_model=ActionCatalogItem, summary="Get action catalog metadata"
)
async def get_action(action_type: str, _: Viewer) -> ActionCatalogItem:
    """Return catalog metadata for a specific operational action."""
    meta = get_action_metadata(action_type)
    return ActionCatalogItem(
        action_type=meta.action_type.value,
        reversible=meta.reversible,
        persistent=meta.persistent,
        allowed_environments=sorted(meta.allowed_environments),
        required_permission=meta.required_permission.value,
        verification_strategy=meta.verification_strategy.value,
        rollback_capable=meta.rollback_capable,
        implemented=meta.implemented,
    )


@router.post("/evaluate", summary="Evaluate action proposal risk and OPA policy")
async def evaluate_action(
    payload: ActionEvaluationRequest,
    _principal: Operator,
    opa: Annotated[OPAClient, Depends(get_opa_client)],
) -> dict[str, Any]:
    """Evaluate risk score and policy decision deterministically for a proposed action."""
    meta = get_action_metadata(payload.action_type)
    target_count = int(payload.parameters.get("target_count", 1))
    context = RiskContext(
        environment=payload.environment.value,
        action=payload.action_type,
        target_count=target_count,
    )
    risk_result = RiskEngine.calculate(context)
    target_input = TargetInput(
        namespace=str(payload.parameters.get("namespace", "default")),
        pod_name=str(payload.parameters.get("pod_name", "workload")),
        labels=dict(payload.parameters.get("labels", {})),
        controller_managed=bool(payload.parameters.get("controller_managed", True)),
        target_pods=target_count,
    )
    policy_input = PolicyInput(
        environment=payload.environment.value,
        action=payload.action_type,
        risk_score=risk_result.score,
        risk_factors=risk_result.factors,
        confidence=float(payload.parameters.get("confidence", 1.0)),
        blast_radius=risk_result.factors.blast_radius,
        reversible=meta.reversible,
        service_criticality=str(payload.parameters.get("service_criticality", "standard")),
        target=target_input,
    )
    opa_decision = await opa.evaluate(policy_input)
    return {
        "action_type": payload.action_type.value,
        "environment": payload.environment.value,
        "risk_score": risk_result.score,
        "classification": risk_result.classification.value,
        "recommended_mode": risk_result.recommended_mode.value,
        "factors": risk_result.factors.model_dump(),
        "policy_allowed": opa_decision.allowed,
        "requires_approval": opa_decision.requires_approval,
        "policy_reason": opa_decision.reason,
    }
