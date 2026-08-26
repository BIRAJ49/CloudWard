from dataclasses import replace

import pytest

from app.kubernetes.executor import DeploymentState, PodState, ServiceHealth
from app.verification import VerificationEngine


def pod(name: str, ready: bool) -> PodState:
    return PodState(
        namespace="cloudward-staging",
        name=name,
        phase="Running",
        ready=ready,
        labels={},
        controller_managed=True,
        controller_kind="ReplicaSet",
        restart_count=0,
    )


class FakeKubernetes:
    def __init__(self, *, replicas: int = 2, ready_pods: int = 2, healthy: bool = True) -> None:
        self.deployment = DeploymentState(
            "cloudward-staging", "cloudward-demo", 2, replicas, replicas, 1
        )
        self.pods = [pod(f"pod-{index}", index < ready_pods) for index in range(2)]
        self.health = ServiceHealth(
            "cloudward-staging", "cloudward-demo", "health/ready", healthy, {"status": "ready"}
        )

    async def get_deployment(self, namespace: str, name: str) -> DeploymentState:
        return self.deployment

    async def get_pods(self, namespace: str, label_selector: str) -> list[PodState]:
        return self.pods

    async def get_service_health(
        self, namespace: str, service_name: str, path: str = "health/ready"
    ) -> ServiceHealth:
        return self.health


@pytest.mark.asyncio
async def test_verification_requires_all_three_signals() -> None:
    result = await VerificationEngine(FakeKubernetes()).check_once(
        namespace="cloudward-staging",
        deployment="cloudward-demo",
        label_selector="app=demo",
        expected_replicas=2,
        service_name="cloudward-demo",
    )
    assert result.success
    assert {check.type for check in result.checks} == {
        "ready_replicas",
        "pod_readiness",
        "health_endpoint",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kubernetes",
    [
        FakeKubernetes(replicas=1),
        FakeKubernetes(ready_pods=1),
        FakeKubernetes(healthy=False),
    ],
)
async def test_any_failed_signal_prevents_resolution(kubernetes: FakeKubernetes) -> None:
    result = await VerificationEngine(kubernetes).check_once(
        namespace="cloudward-staging",
        deployment="cloudward-demo",
        label_selector="app=demo",
        expected_replicas=2,
        service_name="cloudward-demo",
    )
    assert not result.success


@pytest.mark.asyncio
async def test_polling_can_recover_before_timeout() -> None:
    kubernetes = FakeKubernetes(replicas=1)
    calls = 0

    async def deployment(namespace: str, name: str) -> DeploymentState:
        nonlocal calls
        calls += 1
        if calls > 1:
            kubernetes.deployment = replace(
                kubernetes.deployment, ready_replicas=2, available_replicas=2
            )
        return kubernetes.deployment

    kubernetes.get_deployment = deployment  # type: ignore[method-assign]
    result = await VerificationEngine(kubernetes).verify_until(
        namespace="cloudward-staging",
        deployment="cloudward-demo",
        label_selector="app=demo",
        expected_replicas=2,
        service_name="cloudward-demo",
        timeout_seconds=0.2,
        poll_seconds=0.01,
    )
    assert result.success
    assert result.attempts == 2
