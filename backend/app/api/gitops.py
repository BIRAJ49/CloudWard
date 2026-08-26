"""Viewer-safe, read-only GitOps drift visibility."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.api.dependencies import get_kubernetes_executor
from app.auth.schemas import Principal
from app.gitops import GitOpsDriftSnapshot, observe_drift
from app.kubernetes import KubernetesExecutor
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/gitops", tags=["gitops"])
Viewer = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))]

EnvironmentName = Literal["staging", "production"]
ENVIRONMENTS: dict[EnvironmentName, tuple[str, str, str]] = {
    "staging": (
        "cloudward-staging",
        "cloudward-staging",
        "cloudward-staging-cloudward-demo",
    ),
    "production": (
        "cloudward-production",
        "cloudward-production",
        "cloudward-production-cloudward-demo",
    ),
}


@router.get("/drift/{environment}")
async def gitops_drift(
    environment: EnvironmentName,
    _: Viewer,
    kubernetes: Annotated[KubernetesExecutor, Depends(get_kubernetes_executor)],
) -> dict[str, object]:
    application, namespace, deployment = ENVIRONMENTS[environment]
    snapshot: GitOpsDriftSnapshot = await observe_drift(
        kubernetes,
        environment=environment,
        application_name=application,
        namespace=namespace,
        deployment_name=deployment,
    )
    return snapshot.to_dict()
