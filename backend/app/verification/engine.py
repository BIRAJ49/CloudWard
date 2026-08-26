"""Verify Kubernetes reconciliation and application health before resolution."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.kubernetes.executor import DeploymentState, PodState, ServiceHealth


class VerificationKubernetesClient(Protocol):
    async def get_deployment(self, namespace: str, name: str) -> DeploymentState: ...

    async def get_pods(self, namespace: str, label_selector: str) -> list[PodState]: ...

    async def get_service_health(
        self, namespace: str, service_name: str, path: str = "health/ready"
    ) -> ServiceHealth: ...


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str
    expected: Any = None
    actual: Any = None
    passed: bool
    detail: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    success: bool
    checks: list[VerificationCheck]
    attempts: int


class VerificationEngine:
    def __init__(
        self,
        kubernetes: VerificationKubernetesClient,
    ) -> None:
        self.kubernetes = kubernetes

    async def check_once(
        self,
        *,
        namespace: str,
        deployment: str,
        label_selector: str,
        expected_replicas: int,
        service_name: str,
        health_path: str = "health/ready",
    ) -> VerificationResult:
        checks: list[VerificationCheck] = []
        try:
            deployment_state = await self.kubernetes.get_deployment(namespace, deployment)
            checks.append(
                VerificationCheck(
                    type="ready_replicas",
                    expected=expected_replicas,
                    actual=deployment_state.ready_replicas,
                    passed=deployment_state.ready_replicas == expected_replicas,
                )
            )
            pods = await self.kubernetes.get_pods(namespace, label_selector)
            ready_pods = sum(1 for pod in pods if pod.ready)
            checks.append(
                VerificationCheck(
                    type="pod_readiness",
                    expected=expected_replicas,
                    actual=ready_pods,
                    passed=ready_pods == expected_replicas,
                )
            )
        except Exception as exc:  # Kubernetes transport failures are verification failures.
            checks.extend(
                [
                    VerificationCheck(
                        type="ready_replicas",
                        expected=expected_replicas,
                        passed=False,
                        detail=type(exc).__name__,
                    ),
                    VerificationCheck(
                        type="pod_readiness",
                        expected=expected_replicas,
                        passed=False,
                        detail=type(exc).__name__,
                    ),
                ]
            )
        try:
            health = await self.kubernetes.get_service_health(namespace, service_name, health_path)
            checks.append(
                VerificationCheck(
                    type="health_endpoint",
                    expected="healthy",
                    actual="healthy" if health.healthy else "unhealthy",
                    passed=health.healthy,
                )
            )
        except Exception as exc:
            checks.append(
                VerificationCheck(
                    type="health_endpoint",
                    expected="healthy",
                    passed=False,
                    detail=type(exc).__name__,
                )
            )
        return VerificationResult(
            success=all(check.passed for check in checks), checks=checks, attempts=1
        )

    async def verify_until(
        self,
        *,
        namespace: str,
        deployment: str,
        label_selector: str,
        expected_replicas: int,
        service_name: str,
        timeout_seconds: float,
        poll_seconds: float,
        health_path: str = "health/ready",
    ) -> VerificationResult:
        deadline = time.monotonic() + timeout_seconds
        attempts = 0
        last: VerificationResult | None = None
        while True:
            attempts += 1
            last = await self.check_once(
                namespace=namespace,
                deployment=deployment,
                label_selector=label_selector,
                expected_replicas=expected_replicas,
                service_name=service_name,
                health_path=health_path,
            )
            if last.success or time.monotonic() >= deadline:
                return last.model_copy(update={"attempts": attempts})
            await asyncio.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
