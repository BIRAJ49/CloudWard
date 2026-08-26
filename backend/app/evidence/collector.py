"""Structured Part 1 Kubernetes and health evidence collection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.kubernetes.executor import DeploymentState, PodState


class EvidenceKubernetesClient(Protocol):
    async def get_deployment(self, namespace: str, name: str) -> DeploymentState: ...

    async def get_pods(self, namespace: str, label_selector: str) -> list[PodState]: ...


@dataclass(frozen=True, slots=True)
class KubernetesEvidence:
    deployment: DeploymentState
    pods: tuple[PodState, ...]

    @property
    def unhealthy_pods(self) -> tuple[PodState, ...]:
        return tuple(pod for pod in self.pods if not pod.ready)

    def to_payload(self) -> dict[str, Any]:
        return {
            "deployment": self.deployment.to_dict(),
            "pods": [pod.to_dict() for pod in self.pods],
            "unhealthy_pod_count": len(self.unhealthy_pods),
        }


class EvidenceCollector:
    def __init__(self, kubernetes: EvidenceKubernetesClient) -> None:
        self.kubernetes = kubernetes

    async def collect_kubernetes_state(
        self, *, namespace: str, deployment: str, label_selector: str
    ) -> KubernetesEvidence:
        deployment_state = await self.kubernetes.get_deployment(namespace, deployment)
        pods = await self.kubernetes.get_pods(namespace, label_selector)
        return KubernetesEvidence(deployment=deployment_state, pods=tuple(pods))
