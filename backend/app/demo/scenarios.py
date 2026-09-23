"""Closed Incident Lab catalog; users cannot submit executable YAML or commands."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.errors import CloudWardError

DEMO_NAMESPACE = "cloudward-staging"
DEMO_SELECTOR = {"cloudward.io/demo-target": "true"}


class ScenarioCategory(StrEnum):
    RELIABILITY = "reliability"
    SECURITY = "security"
    FINOPS = "finops"


class ScenarioMechanism(StrEnum):
    GITOPS_RELEASE = "GITOPS_RELEASE"
    STRESS_CHAOS = "STRESS_CHAOS"
    POD_CHAOS = "POD_CHAOS"
    SAFE_DEMO_ENDPOINT = "SAFE_DEMO_ENDPOINT"
    FINOPS_ANALYSIS = "FINOPS_ANALYSIS"


class ChaosScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    description: str
    category: ScenarioCategory
    mechanism: ScenarioMechanism
    target_namespace: str = DEMO_NAMESPACE
    target_selector: dict[str, str] = Field(default_factory=lambda: dict(DEMO_SELECTOR))
    duration_seconds: int = Field(ge=5, le=300)
    expected_alert: str
    expected_runbook: str
    expected_signals: tuple[str, ...]
    cleanup_strategy: str
    max_runtime_seconds: int = Field(ge=30, le=600)


SCENARIOS: tuple[ChaosScenario, ...] = (
    ChaosScenario(
        id="reliability.bad-deployment",
        name="Bad deployment",
        description="Deploy a fixed bad demo image and recover its known-good GitOps revision.",
        category=ScenarioCategory.RELIABILITY,
        mechanism=ScenarioMechanism.GITOPS_RELEASE,
        duration_seconds=120,
        expected_alert="HighHTTPErrorRate",
        expected_runbook="reliability.bad-deployment",
        expected_signals=("http_5xx_rate", "deployment_revision", "logs", "traces"),
        cleanup_strategy="restore_known_good_gitops_revision",
        max_runtime_seconds=300,
    ),
    ChaosScenario(
        id="reliability.cpu-saturation",
        name="CPU saturation",
        description="Apply bounded Chaos Mesh CPU pressure to demo-labeled staging pods.",
        category=ScenarioCategory.RELIABILITY,
        mechanism=ScenarioMechanism.STRESS_CHAOS,
        duration_seconds=90,
        expected_alert="HighCPUSaturation",
        expected_runbook="reliability.cpu-saturation",
        expected_signals=("container_cpu", "p95_latency", "ready_replicas"),
        cleanup_strategy="delete_stresschaos",
        max_runtime_seconds=240,
    ),
    ChaosScenario(
        id="reliability.memory-pressure",
        name="Memory pressure / OOM",
        description="Apply bounded container memory stress without exhausting the host.",
        category=ScenarioCategory.RELIABILITY,
        mechanism=ScenarioMechanism.STRESS_CHAOS,
        duration_seconds=60,
        expected_alert="ContainerOOMKilled",
        expected_runbook="reliability.memory-pressure",
        expected_signals=("memory_working_set", "oom_reason", "restart_count", "events"),
        cleanup_strategy="delete_stresschaos",
        max_runtime_seconds=240,
    ),
    ChaosScenario(
        id="reliability.platform-self-healing",
        name="Kubernetes self-healing",
        description="Kill one demo pod and attribute its replacement to Kubernetes.",
        category=ScenarioCategory.RELIABILITY,
        mechanism=ScenarioMechanism.POD_CHAOS,
        duration_seconds=30,
        expected_alert="WorkloadUnavailable",
        expected_runbook="reliability.platform-self-healing",
        expected_signals=("pod_uid_changed", "ready_replicas", "health_check"),
        cleanup_strategy="delete_podchaos",
        max_runtime_seconds=180,
    ),
    ChaosScenario(
        id="security.suspicious-shell-pattern",
        name="Suspicious shell pattern",
        description="Run one harmless fixed shell child and an internal-only connectivity probe.",
        category=ScenarioCategory.SECURITY,
        mechanism=ScenarioMechanism.SAFE_DEMO_ENDPOINT,
        duration_seconds=30,
        expected_alert="TetragonUnexpectedShell",
        expected_runbook="security.suspicious-shell-pattern",
        expected_signals=("tetragon_process_exec", "normalized_security_event"),
        cleanup_strategy="remove_quarantine_and_demo_state",
        max_runtime_seconds=180,
    ),
    ChaosScenario(
        id="security.unexpected-egress",
        name="Unexpected internal egress",
        description="Connect only to the in-cluster c2-simulator before and after quarantine.",
        category=ScenarioCategory.SECURITY,
        mechanism=ScenarioMechanism.SAFE_DEMO_ENDPOINT,
        duration_seconds=30,
        expected_alert="TetragonUnexpectedEgress",
        expected_runbook="security.unexpected-egress",
        expected_signals=("internal_connect", "cilium_policy_verification"),
        cleanup_strategy="remove_quarantine_and_demo_state",
        max_runtime_seconds=180,
    ),
    ChaosScenario(
        id="security.privilege-related-behavior",
        name="Privilege-related behavior",
        description="Attempt a benign denied read of /proc/1/mem; no exploit or escape.",
        category=ScenarioCategory.SECURITY,
        mechanism=ScenarioMechanism.SAFE_DEMO_ENDPOINT,
        duration_seconds=30,
        expected_alert="TetragonPrivilegeBehavior",
        expected_runbook="security.privilege-related-behavior",
        expected_signals=("tetragon_privilege_event", "denied_operation"),
        cleanup_strategy="remove_quarantine_and_demo_state",
        max_runtime_seconds=180,
    ),
    ChaosScenario(
        id="finops.overprovisioned-workload",
        name="Overprovisioned workload",
        description="Analyze observed demo workload utilization and OpenCost allocation with deterministic safety headroom.",
        category=ScenarioCategory.FINOPS,
        mechanism=ScenarioMechanism.FINOPS_ANALYSIS,
        duration_seconds=30,
        expected_alert="FinOpsAnalysisComplete",
        expected_runbook="finops.workload-rightsizing",
        expected_signals=("cpu_p95", "memory_p95", "resource_requests", "opencost_allocation"),
        cleanup_strategy="analysis_only_no_live_mutation",
        max_runtime_seconds=180,
    ),
    ChaosScenario(
        id="finops.wasted-node-capacity",
        name="Wasted node capacity",
        description="Analyze node allocatable capacity, requests, observed usage, pod distribution, and local OpenCost allocation.",
        category=ScenarioCategory.FINOPS,
        mechanism=ScenarioMechanism.FINOPS_ANALYSIS,
        duration_seconds=30,
        expected_alert="FinOpsAnalysisComplete",
        expected_runbook="finops.node-efficiency",
        expected_signals=(
            "node_allocatable",
            "scheduled_requests",
            "node_usage_p95",
            "opencost_allocation",
        ),
        cleanup_strategy="analysis_only_no_live_mutation",
        max_runtime_seconds=180,
    ),
)

_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


def get_scenario(scenario_id: str) -> ChaosScenario:
    try:
        return _BY_ID[scenario_id]
    except KeyError as exc:
        raise CloudWardError(
            "SCENARIO_NOT_FOUND", "Incident Lab scenario was not found", status_code=404
        ) from exc
