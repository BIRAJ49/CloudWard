from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import CloudWardError
from app.kubernetes.executor import KubernetesExecutor


def fake_pod(*, ready: bool, labels: dict[str, str], kind: str = "ReplicaSet") -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(
            namespace="cloudward-staging",
            name="cloudward-demo-abc",
            labels=labels,
            owner_references=[SimpleNamespace(controller=True, kind=kind)],
        ),
        status=SimpleNamespace(
            phase="Running",
            conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
            container_statuses=[SimpleNamespace(restart_count=2)],
        ),
    )


def executor(pod: SimpleNamespace) -> tuple[KubernetesExecutor, AsyncMock]:
    core = AsyncMock()
    core.read_namespaced_pod.return_value = pod
    return (
        KubernetesExecutor(core, AsyncMock(), allowed_namespaces=frozenset({"cloudward-staging"})),
        core,
    )


@pytest.mark.asyncio
async def test_deletes_only_unhealthy_controlled_replicaset_pod() -> None:
    kube, core = executor(fake_pod(ready=False, labels={"cloudward.io/demo-target": "true"}))
    result = await kube.delete_pod("cloudward-staging", "cloudward-demo-abc")
    assert result.accepted
    assert result.controller_reconciles_replacement
    core.delete_namespaced_pod.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pod", "namespace", "code"),
    [
        (
            fake_pod(ready=False, labels={"cloudward.io/demo-target": "true"}),
            "cloudward-production",
            "KUBERNETES_NAMESPACE_DENIED",
        ),
        (fake_pod(ready=False, labels={}), "cloudward-staging", "KUBERNETES_TARGET_DENIED"),
        (
            fake_pod(
                ready=False,
                labels={"cloudward.io/demo-target": "true"},
                kind="Job",
            ),
            "cloudward-staging",
            "KUBERNETES_TARGET_DENIED",
        ),
        (
            fake_pod(ready=True, labels={"cloudward.io/demo-target": "true"}),
            "cloudward-staging",
            "KUBERNETES_TARGET_HEALTHY",
        ),
    ],
)
async def test_unsafe_pod_deletion_is_rejected(
    pod: SimpleNamespace, namespace: str, code: str
) -> None:
    kube, core = executor(pod)
    with pytest.raises(CloudWardError) as caught:
        await kube.delete_pod(namespace, "cloudward-demo-abc")
    assert caught.value.code == code
    core.delete_namespaced_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_health_uses_kubernetes_proxy() -> None:
    kube, core = executor(fake_pod(ready=False, labels={"cloudward.io/demo-target": "true"}))
    core.connect_get_namespaced_service_proxy_with_path.return_value = {"status": "ready"}
    health = await kube.get_service_health("cloudward-staging", "cloudward-demo", "health/ready")
    assert health.healthy
    core.connect_get_namespaced_service_proxy_with_path.assert_awaited_once_with(
        "cloudward-demo", "cloudward-staging", "health/ready"
    )
