from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.gitops import DriftClassification, observe_drift
from app.kubernetes.executor import ArgoApplicationState, DeploymentState


class FakeKubernetesExecutor:
    def __init__(self, application: ArgoApplicationState, deployment: DeploymentState) -> None:
        self.application = application
        self.deployment = deployment

    async def get_argocd_application(self, name: str) -> ArgoApplicationState:
        assert name == self.application.name
        return self.application

    async def get_deployment(self, namespace: str, name: str) -> DeploymentState:
        assert namespace == self.deployment.namespace
        assert name == self.deployment.name
        return self.deployment


@pytest.fixture
def argo_state() -> ArgoApplicationState:
    return ArgoApplicationState(
        name="cloudward-staging",
        target_revision="main",
        observed_revision="a" * 40,
        sync_status="Synced",
        health_status="Healthy",
        operation_phase="Succeeded",
        reconciled_at="2026-08-22T00:00:00Z",
        out_of_sync_resources=(),
    )


@pytest.fixture
def deployment_state() -> DeploymentState:
    return DeploymentState(
        namespace="cloudward-staging",
        name="cloudward-staging-cloudward-demo",
        desired_replicas=2,
        ready_replicas=2,
        available_replicas=2,
        observed_generation=3,
        container_images=("ghcr.io/biraj49/cloudward-demo-api@sha256:" + "1" * 64,),
    )


async def snapshot(argo_state: ArgoApplicationState, deployment_state: DeploymentState) -> Any:
    return await observe_drift(  # type: ignore[arg-type]
        FakeKubernetesExecutor(argo_state, deployment_state),
        environment="staging",
        application_name=argo_state.name,
        namespace=deployment_state.namespace,
        deployment_name=deployment_state.name,
    )


@pytest.mark.asyncio
async def test_reconciled_digest_is_not_drift(
    argo_state: ArgoApplicationState, deployment_state: DeploymentState
) -> None:
    result = await snapshot(argo_state, deployment_state)
    assert result.classification is DriftClassification.RECONCILED
    assert result.persistent_drift is False


@pytest.mark.asyncio
async def test_argo_out_of_sync_is_persistent_drift(
    argo_state: ArgoApplicationState, deployment_state: DeploymentState
) -> None:
    drifted = replace(
        argo_state,
        sync_status="OutOfSync",
        out_of_sync_resources=(
            {
                "group": "apps",
                "kind": "Deployment",
                "namespace": "cloudward-staging",
                "name": deployment_state.name,
                "status": "OutOfSync",
            },
        ),
    )
    result = await snapshot(drifted, deployment_state)
    assert result.classification is DriftClassification.PERSISTENT_GITOPS_DRIFT
    assert result.persistent_drift is True


@pytest.mark.asyncio
async def test_mutable_image_is_supply_chain_violation(
    argo_state: ArgoApplicationState, deployment_state: DeploymentState
) -> None:
    mutable = replace(
        deployment_state,
        container_images=("ghcr.io/biraj49/cloudward-demo-api:latest",),
    )
    result = await snapshot(argo_state, mutable)
    assert result.classification is DriftClassification.SUPPLY_CHAIN_VIOLATION
    assert result.all_images_digest_pinned is False
    assert result.persistent_drift is True
