"""Classify persistent GitOps drift separately from temporary operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.kubernetes import KubernetesExecutor


class DriftClassification(StrEnum):
    RECONCILED = "reconciled"
    PERSISTENT_GITOPS_DRIFT = "persistent_gitops_drift"
    SUPPLY_CHAIN_VIOLATION = "supply_chain_violation"


@dataclass(frozen=True, slots=True)
class GitOpsDriftSnapshot:
    environment: str
    application: str
    target_revision: str
    observed_revision: str | None
    sync_status: str
    health_status: str
    operation_phase: str | None
    reconciled_at: str | None
    deployment: str
    deployed_images: tuple[str, ...]
    all_images_digest_pinned: bool
    out_of_sync_resources: tuple[dict[str, str], ...]
    classification: DriftClassification
    persistent_drift: bool
    direct_operation_classification: str = "temporary_actions_are_not_gitops_drift"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def observe_drift(
    kubernetes: KubernetesExecutor,
    *,
    environment: str,
    application_name: str,
    namespace: str,
    deployment_name: str,
) -> GitOpsDriftSnapshot:
    application = await kubernetes.get_argocd_application(application_name)
    deployment = await kubernetes.get_deployment(namespace, deployment_name)
    images = deployment.container_images
    immutable = bool(images) and all("@sha256:" in image for image in images)

    if not immutable:
        classification = DriftClassification.SUPPLY_CHAIN_VIOLATION
    elif application.has_persistent_drift:
        classification = DriftClassification.PERSISTENT_GITOPS_DRIFT
    else:
        classification = DriftClassification.RECONCILED

    return GitOpsDriftSnapshot(
        environment=environment,
        application=application.name,
        target_revision=application.target_revision,
        observed_revision=application.observed_revision,
        sync_status=application.sync_status,
        health_status=application.health_status,
        operation_phase=application.operation_phase,
        reconciled_at=application.reconciled_at,
        deployment=deployment_name,
        deployed_images=images,
        all_images_digest_pinned=immutable,
        out_of_sync_resources=application.out_of_sync_resources,
        classification=classification,
        persistent_drift=(application.has_persistent_drift or not immutable),
    )
