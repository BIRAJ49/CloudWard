"""Construct only allowlisted Chaos Mesh resources for reliability scenarios."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.demo.scenarios import ChaosScenario, ScenarioMechanism
from app.errors import CloudWardError
from app.kubernetes import KubernetesExecutor

CHAOS_GROUP = "chaos-mesh.org"
CHAOS_VERSION = "v1alpha1"


@dataclass(frozen=True, slots=True)
class StartedScenarioResource:
    kind: str
    plural: str
    name: str


def _metadata(execution_id: uuid.UUID, scenario: ChaosScenario) -> dict[str, Any]:
    return {
        "name": f"cloudward-{str(execution_id)[:12]}",
        "namespace": scenario.target_namespace,
        "labels": {
            "app.kubernetes.io/managed-by": "cloudward",
            "cloudward.io/scenario": scenario.id.replace(".", "-")[:63],
            "cloudward.io/execution": str(execution_id),
        },
    }


def _selector(scenario: ChaosScenario) -> dict[str, Any]:
    if scenario.target_namespace != "cloudward-staging" or scenario.target_selector != {
        "cloudward.io/demo-target": "true"
    }:
        raise CloudWardError(
            "CHAOS_TARGET_DENIED", "Chaos target violates the immutable staging policy", status_code=403
        )
    return {
        "namespaces": ["cloudward-staging"],
        "labelSelectors": {"cloudward.io/demo-target": "true"},
    }


class ChaosMeshScenarioExecutor:
    def __init__(self, kubernetes: KubernetesExecutor) -> None:
        self.kubernetes = kubernetes

    async def start(
        self, scenario: ChaosScenario, execution_id: uuid.UUID
    ) -> StartedScenarioResource:
        metadata = _metadata(execution_id, scenario)
        if scenario.mechanism == ScenarioMechanism.STRESS_CHAOS:
            stressors: dict[str, Any]
            if scenario.id == "reliability.cpu-saturation":
                stressors = {"cpu": {"workers": 1, "load": 80}}
            elif scenario.id == "reliability.memory-pressure":
                stressors = {"memory": {"workers": 1, "size": "96MB"}}
            else:
                raise CloudWardError("SCENARIO_NOT_EXECUTABLE", "Unknown stress scenario")
            body = {
                "apiVersion": f"{CHAOS_GROUP}/{CHAOS_VERSION}",
                "kind": "StressChaos",
                "metadata": metadata,
                "spec": {
                    "mode": "one",
                    "selector": _selector(scenario),
                    "stressors": stressors,
                    "duration": f"{scenario.duration_seconds}s",
                },
            }
            plural, kind = "stresschaos", "StressChaos"
        elif scenario.mechanism == ScenarioMechanism.POD_CHAOS:
            body = {
                "apiVersion": f"{CHAOS_GROUP}/{CHAOS_VERSION}",
                "kind": "PodChaos",
                "metadata": metadata,
                "spec": {
                    "action": "pod-kill",
                    "mode": "one",
                    "selector": _selector(scenario),
                    "duration": f"{scenario.duration_seconds}s",
                    "gracePeriod": 0,
                },
            }
            plural, kind = "podchaos", "PodChaos"
        else:
            raise CloudWardError(
                "SCENARIO_REQUIRES_TYPED_WORKER",
                "This scenario is executed by its fixed GitOps or security worker",
                status_code=409,
            )
        await self.kubernetes.create_typed_custom_object(
            namespace=scenario.target_namespace,
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            plural=plural,
            body=body,
        )
        return StartedScenarioResource(kind=kind, plural=plural, name=metadata["name"])

    async def cleanup(self, *, namespace: str, kind: str, name: str) -> None:
        plural = {"StressChaos": "stresschaos", "PodChaos": "podchaos"}.get(kind)
        if plural is None:
            return
        await self.kubernetes.delete_typed_custom_object(
            namespace=namespace,
            name=name,
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            plural=plural,
        )
