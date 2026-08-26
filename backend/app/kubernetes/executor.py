"""Narrow typed Kubernetes executor; no shell or arbitrary kubectl execution exists."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.config.config_exception import ConfigException

from app.errors import CloudWardError

DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
SAFE_SELECTOR = re.compile(r"^[A-Za-z0-9./_=,!() -]{1,512}$")
DEMO_TARGET_LABEL = "cloudward.io/demo-target"
QUARANTINE_LABEL = "cloudward.io/quarantine-id"
SECURITY_SCENARIO_PATHS = {
    "security.suspicious-shell-pattern": "demo/security/suspicious-shell",
    "security.unexpected-egress": "demo/security/unexpected-egress",
    "security.privilege-related-behavior": "demo/security/privilege-attempt",
}


@dataclass(frozen=True, slots=True)
class DeploymentState:
    namespace: str
    name: str
    desired_replicas: int
    ready_replicas: int
    available_replicas: int
    observed_generation: int | None
    container_images: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PodState:
    namespace: str
    name: str
    phase: str
    ready: bool
    labels: dict[str, str]
    controller_managed: bool
    controller_kind: str | None
    restart_count: int
    termination_reasons: tuple[str, ...] = ()
    exit_codes: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PodDeletionResult:
    namespace: str
    pod_name: str
    accepted: bool
    controller_reconciles_replacement: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DeploymentScaleResult:
    namespace: str
    deployment: str
    previous_replicas: int
    requested_replicas: int
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    namespace: str
    service_name: str
    path: str
    healthy: bool
    payload: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ControlledEgressProbe:
    namespace: str
    pod_name: str
    reachable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QuarantinePolicyResult:
    namespace: str
    pod_name: str
    policy_name: str
    quarantine_id: str
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QuarantinePolicyState:
    namespace: str
    pod_name: str
    policy_name: str
    policy_exists: bool
    target_label_matches: bool
    deny_all_egress: bool

    @property
    def enforced(self) -> bool:
        return self.policy_exists and self.target_label_matches and self.deny_all_egress

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "enforced": self.enforced}


@dataclass(frozen=True, slots=True)
class SecurityScenarioTriggerResult:
    scenario_id: str
    namespace: str
    pod_name: str
    endpoint: str
    result: dict[str, bool | str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArgoApplicationState:
    name: str
    target_revision: str
    observed_revision: str | None
    sync_status: str
    health_status: str
    operation_phase: str | None
    reconciled_at: str | None
    out_of_sync_resources: tuple[dict[str, str], ...]

    @property
    def has_persistent_drift(self) -> bool:
        return self.sync_status != "Synced" or bool(self.out_of_sync_resources)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "has_persistent_drift": self.has_persistent_drift}


def _validate_name(value: str, label: str) -> None:
    if len(value) > 253 or not DNS_LABEL.fullmatch(value):
        raise CloudWardError("INVALID_KUBERNETES_TARGET", f"Invalid {label}", status_code=422)


class KubernetesExecutor:
    """Only exposes the typed operations needed by deterministic Part 1 remediation."""

    def __init__(
        self,
        core_api: Any,
        apps_api: Any,
        *,
        allowed_namespaces: frozenset[str],
        custom_api: Any | None = None,
        api_client: client.ApiClient | None = None,
    ) -> None:
        self.core_api = core_api
        self.apps_api = apps_api
        self.allowed_namespaces = allowed_namespaces
        self.custom_api = custom_api
        self._api_client = api_client

    @classmethod
    async def create(
        cls, *, context: str | None, allowed_namespaces: frozenset[str]
    ) -> KubernetesExecutor:
        try:
            config.load_incluster_config()  # type: ignore[no-untyped-call]
        except ConfigException:
            await config.load_kube_config(context=context)
        api_client = client.ApiClient()
        return cls(
            client.CoreV1Api(api_client),
            client.AppsV1Api(api_client),
            allowed_namespaces=allowed_namespaces,
            custom_api=client.CustomObjectsApi(api_client),
            api_client=api_client,
        )

    async def close(self) -> None:
        if self._api_client is not None:
            await self._api_client.close()

    def _require_namespace(self, namespace: str) -> None:
        _validate_name(namespace, "namespace")
        if namespace not in self.allowed_namespaces:
            raise CloudWardError(
                "KUBERNETES_NAMESPACE_DENIED",
                f"Automated actions are not allowed in namespace {namespace}",
                status_code=403,
            )

    async def get_deployment(self, namespace: str, name: str) -> DeploymentState:
        _validate_name(namespace, "namespace")
        _validate_name(name, "deployment name")
        try:
            deployment = await self.apps_api.read_namespaced_deployment(name, namespace)
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_API_ERROR",
                "Unable to read Kubernetes deployment",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        spec_replicas = deployment.spec.replicas or 0
        status = deployment.status
        return DeploymentState(
            namespace=namespace,
            name=name,
            desired_replicas=spec_replicas,
            ready_replicas=status.ready_replicas or 0,
            available_replicas=status.available_replicas or 0,
            observed_generation=status.observed_generation,
            container_images=tuple(
                container.image for container in (deployment.spec.template.spec.containers or [])
            ),
        )

    async def get_argocd_application(self, name: str) -> ArgoApplicationState:
        """Read Argo's observed Git state without mutating Kubernetes."""

        _validate_name(name, "Argo CD application name")
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_CLIENT_UNAVAILABLE",
                "The Kubernetes custom resources client is unavailable",
                status_code=503,
            )
        try:
            application = await self.custom_api.get_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace="argocd",
                plural="applications",
                name=name,
            )
        except ApiException as exc:
            raise CloudWardError(
                "ARGOCD_API_ERROR",
                "Unable to read Argo CD application status",
                status_code=502,
                details={"status": exc.status, "application": name},
            ) from exc

        spec = application.get("spec") or {}
        status = application.get("status") or {}
        source = spec.get("source") or {}
        sync = status.get("sync") or {}
        health = status.get("health") or {}
        operation_state = status.get("operationState") or {}
        resources = status.get("resources") or []
        out_of_sync_resources = tuple(
            {
                "group": str(resource.get("group") or ""),
                "kind": str(resource.get("kind") or ""),
                "namespace": str(resource.get("namespace") or ""),
                "name": str(resource.get("name") or ""),
                "status": str(resource.get("status") or "Unknown"),
            }
            for resource in resources
            if resource.get("status") != "Synced"
        )
        return ArgoApplicationState(
            name=name,
            target_revision=str(source.get("targetRevision") or ""),
            observed_revision=(str(sync["revision"]) if sync.get("revision") else None),
            sync_status=str(sync.get("status") or "Unknown"),
            health_status=str(health.get("status") or "Unknown"),
            operation_phase=(
                str(operation_state["phase"]) if operation_state.get("phase") else None
            ),
            reconciled_at=(
                str(status["reconciledAt"]) if status.get("reconciledAt") else None
            ),
            out_of_sync_resources=out_of_sync_resources,
        )

    async def get_pods(self, namespace: str, label_selector: str) -> list[PodState]:
        _validate_name(namespace, "namespace")
        if not SAFE_SELECTOR.fullmatch(label_selector):
            raise CloudWardError("INVALID_KUBERNETES_SELECTOR", "Invalid label selector")
        try:
            response = await self.core_api.list_namespaced_pod(
                namespace, label_selector=label_selector
            )
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_API_ERROR",
                "Unable to list Kubernetes pods",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        return [self._pod_state(pod) for pod in response.items]

    async def get_pod_health(self, namespace: str, name: str) -> PodState:
        _validate_name(namespace, "namespace")
        _validate_name(name, "pod name")
        try:
            pod = await self.core_api.read_namespaced_pod(name, namespace)
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_API_ERROR",
                "Unable to read Kubernetes pod",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        return self._pod_state(pod)

    async def delete_pod(self, namespace: str, name: str) -> PodDeletionResult:
        """Delete exactly one unhealthy, controlled, ReplicaSet-managed demo pod."""

        self._require_namespace(namespace)
        pod = await self.get_pod_health(namespace, name)
        if pod.labels.get(DEMO_TARGET_LABEL) != "true":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Pod is not labeled as a CloudWard demo target",
                status_code=403,
            )
        if not pod.controller_managed or pod.controller_kind != "ReplicaSet":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Pod is not managed by a ReplicaSet controller",
                status_code=403,
            )
        if pod.ready:
            raise CloudWardError(
                "KUBERNETES_TARGET_HEALTHY",
                "Refusing to delete a ready pod",
                status_code=409,
            )
        try:
            await self.core_api.delete_namespaced_pod(
                name,
                namespace,
                body=client.V1DeleteOptions(
                    grace_period_seconds=0, propagation_policy="Background"
                ),
            )
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_ACTION_FAILED",
                "Kubernetes rejected the typed pod deletion",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        return PodDeletionResult(
            namespace=namespace,
            pod_name=name,
            accepted=True,
            controller_reconciles_replacement=True,
        )

    async def scale_staging_deployment(
        self,
        namespace: str,
        name: str,
        *,
        replicas: int,
        maximum_replicas: int,
        expected_current_replicas: int | None = None,
    ) -> DeploymentScaleResult:
        """Apply a bounded, reversible scale subresource patch to a demo Deployment."""

        self._require_namespace(namespace)
        _validate_name(name, "deployment name")
        if namespace != "cloudward-staging":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED", "Automatic scale is staging-only", status_code=403
            )
        if replicas < 1 or maximum_replicas < 1 or replicas > maximum_replicas:
            raise CloudWardError(
                "SCALE_BOUND_EXCEEDED",
                "Requested replica count exceeds the configured automatic scale bound",
                status_code=422,
            )
        try:
            deployment = await self.apps_api.read_namespaced_deployment(name, namespace)
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_API_ERROR",
                "Unable to read Kubernetes deployment",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        labels = dict(deployment.spec.template.metadata.labels or {})
        if labels.get(DEMO_TARGET_LABEL) != "true":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Deployment is not labeled as a CloudWard demo target",
                status_code=403,
            )
        current = deployment.spec.replicas or 0
        if expected_current_replicas is not None and current != expected_current_replicas:
            raise CloudWardError(
                "STALE_ACTION_TARGET",
                "Deployment replicas changed after the action was proposed",
                status_code=409,
                details={"expected": expected_current_replicas, "actual": current},
            )
        try:
            await self.apps_api.patch_namespaced_deployment_scale(
                name,
                namespace,
                {"spec": {"replicas": replicas}},
            )
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_ACTION_FAILED",
                "Kubernetes rejected the bounded scale action",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        return DeploymentScaleResult(
            namespace=namespace,
            deployment=name,
            previous_replicas=current,
            requested_replicas=replicas,
            accepted=True,
        )

    async def get_events(self, namespace: str, object_name: str) -> list[dict[str, Any]]:
        _validate_name(namespace, "namespace")
        _validate_name(object_name, "object name")
        selector = f"involvedObject.name={object_name}"
        try:
            response = await self.core_api.list_namespaced_event(namespace, field_selector=selector)
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_API_ERROR",
                "Unable to list Kubernetes events",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        return [
            {
                "reason": item.reason,
                "type": item.type,
                "message": item.message,
                "count": item.count,
            }
            for item in response.items[-50:]
        ]

    async def get_service_health(
        self, namespace: str, service_name: str, path: str = "health/ready"
    ) -> ServiceHealth:
        """Reach a ClusterIP service through the authenticated Kubernetes API proxy."""

        _validate_name(namespace, "namespace")
        _validate_name(service_name, "service name")
        normalized_path = path.strip("/")
        if not normalized_path or not re.fullmatch(r"[A-Za-z0-9._~/-]{1,256}", normalized_path):
            raise CloudWardError("INVALID_HEALTH_PATH", "Invalid service health path")
        try:
            payload = await self.core_api.connect_get_namespaced_service_proxy_with_path(
                service_name, namespace, normalized_path
            )
        except ApiException as exc:
            return ServiceHealth(
                namespace=namespace,
                service_name=service_name,
                path=normalized_path,
                healthy=False,
                payload={"status": exc.status},
            )
        healthy = True
        if isinstance(payload, dict):
            status = str(payload.get("status", payload.get("state", "ok"))).lower()
            healthy = status in {"ok", "healthy", "ready", "up", "true"}
        return ServiceHealth(
            namespace=namespace,
            service_name=service_name,
            path=normalized_path,
            healthy=healthy,
            payload=payload,
        )

    async def probe_controlled_security_egress(
        self, namespace: str, pod_name: str
    ) -> ControlledEgressProbe:
        """Invoke the demo pod's fixed internal-only probe; no URL or command is accepted."""

        self._require_namespace(namespace)
        _validate_name(pod_name, "pod name")
        pod = await self.get_pod_health(namespace, pod_name)
        if pod.labels.get(DEMO_TARGET_LABEL) != "true":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Pod is not labeled as a CloudWard demo target",
                status_code=403,
            )
        try:
            payload = await self.core_api.connect_get_namespaced_pod_proxy_with_path(
                pod_name, namespace, "demo/security/egress-probe"
            )
        except ApiException as exc:
            raise CloudWardError(
                "SECURITY_PROBE_FAILED",
                "Unable to execute the controlled egress probe",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise CloudWardError(
                    "SECURITY_PROBE_INVALID",
                    "Controlled egress probe returned an invalid response",
                    status_code=502,
                ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("reachable"), bool):
            raise CloudWardError(
                "SECURITY_PROBE_INVALID",
                "Controlled egress probe returned an invalid response",
                status_code=502,
            )
        return ControlledEgressProbe(
            namespace=namespace, pod_name=pod_name, reachable=payload["reachable"]
        )

    async def trigger_controlled_security_scenario(
        self,
        namespace: str,
        pod_name: str,
        scenario_id: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> SecurityScenarioTriggerResult:
        """Call one catalogued demo endpoint; callers cannot supply a path, URL, or command."""

        self._require_namespace(namespace)
        if namespace != "cloudward-staging":
            raise CloudWardError(
                "SECURITY_SCENARIO_NAMESPACE_DENIED",
                "Runtime-security scenarios are restricted to cloudward-staging",
                status_code=403,
            )
        _validate_name(pod_name, "pod name")
        endpoint = SECURITY_SCENARIO_PATHS.get(scenario_id)
        if endpoint is None:
            raise CloudWardError(
                "SECURITY_SCENARIO_DENIED",
                "Security scenario is not in the fixed executable catalog",
                status_code=422,
            )
        pod = await self.get_pod_health(namespace, pod_name)
        if pod.labels.get(DEMO_TARGET_LABEL) != "true" or not pod.controller_managed:
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Security scenario target is outside the controlled demo boundary",
                status_code=403,
            )
        if not 1 <= timeout_seconds <= 10:
            raise CloudWardError(
                "SECURITY_SCENARIO_TIMEOUT_INVALID",
                "Security scenario timeout is outside the fixed bound",
                status_code=422,
            )
        try:
            async with asyncio.timeout(timeout_seconds):
                payload = await self.core_api.connect_get_namespaced_pod_proxy_with_path(
                    pod_name, namespace, endpoint
                )
        except TimeoutError as exc:
            raise CloudWardError(
                "SECURITY_SCENARIO_TRIGGER_TIMEOUT",
                "Controlled security scenario trigger timed out",
                status_code=504,
            ) from exc
        except ApiException as exc:
            raise CloudWardError(
                "SECURITY_SCENARIO_TRIGGER_FAILED",
                "Kubernetes rejected the controlled security scenario trigger",
                status_code=502,
                details={"status": exc.status},
            ) from exc
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise CloudWardError(
                    "SECURITY_SCENARIO_RESPONSE_INVALID",
                    "Controlled security scenario returned an invalid response",
                    status_code=502,
                ) from exc
        if not isinstance(payload, dict) or payload.get("scenario") != scenario_id:
            raise CloudWardError(
                "SECURITY_SCENARIO_RESPONSE_INVALID",
                "Controlled security scenario returned an invalid response",
                status_code=502,
            )
        safe_result = self._security_scenario_result(scenario_id, payload)
        return SecurityScenarioTriggerResult(
            scenario_id=scenario_id,
            namespace=namespace,
            pod_name=pod_name,
            endpoint=f"/{endpoint}",
            result=safe_result,
        )

    @staticmethod
    def _security_scenario_result(
        scenario_id: str, payload: dict[str, Any]
    ) -> dict[str, bool | str]:
        if scenario_id == "security.suspicious-shell-pattern":
            result: dict[str, bool | str] = {
                "shell_signal": str(payload.get("shell_signal", "")),
                "internal_simulator_reachable": bool(
                    payload.get("internal_simulator_reachable", False)
                ),
                "external_connection": bool(payload.get("external_connection", True)),
            }
            safe = (
                result["shell_signal"] == "completed"
                and result["internal_simulator_reachable"] is True
                and result["external_connection"] is False
            )
        elif scenario_id == "security.unexpected-egress":
            result = {
                "target": str(payload.get("target", "")),
                "reachable": bool(payload.get("reachable", False)),
                "external_connection": bool(payload.get("external_connection", True)),
            }
            safe = (
                result["target"] == "internal-c2-simulator"
                and result["reachable"] is True
                and result["external_connection"] is False
            )
        else:
            result = {
                "operation": str(payload.get("operation", "")),
                "denied": bool(payload.get("denied", False)),
                "exploit_attempted": bool(payload.get("exploit_attempted", True)),
            }
            safe = (
                result["operation"] == "controlled-read-/proc/1/mem"
                and result["denied"] is True
                and result["exploit_attempted"] is False
            )
        if not safe:
            raise CloudWardError(
                "SECURITY_SCENARIO_SAFETY_CHECK_FAILED",
                "Controlled security scenario did not satisfy its fixed safety contract",
                status_code=502,
            )
        return result

    async def apply_quarantine_policy(
        self,
        namespace: str,
        pod_name: str,
        *,
        quarantine_id: str,
        incident_id: str,
    ) -> QuarantinePolicyResult:
        """Apply one typed Cilium egress deny to one live, labeled staging pod."""

        self._require_namespace(namespace)
        if namespace != "cloudward-staging":
            raise CloudWardError(
                "QUARANTINE_NAMESPACE_DENIED",
                "Part 2 quarantine is restricted to cloudward-staging",
                status_code=403,
            )
        _validate_name(pod_name, "pod name")
        _validate_name(quarantine_id, "quarantine id")
        pod = await self.get_pod_health(namespace, pod_name)
        if pod.labels.get(DEMO_TARGET_LABEL) != "true":
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Pod is not labeled as a CloudWard demo target",
                status_code=403,
            )
        if not pod.controller_managed:
            raise CloudWardError(
                "KUBERNETES_TARGET_DENIED",
                "Quarantine target must be a controller-managed demo pod",
                status_code=403,
            )
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_ACTION_UNAVAILABLE",
                "Cilium quarantine client is unavailable",
                status_code=503,
            )
        policy_name = f"cloudward-quarantine-{quarantine_id}"
        _validate_name(policy_name, "policy name")
        selector = {QUARANTINE_LABEL: quarantine_id}
        body = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {"app.kubernetes.io/managed-by": "cloudward"},
                "annotations": {
                    "cloudward.io/incident-id": incident_id,
                    "cloudward.io/target-pod": pod_name,
                },
            },
            "spec": {
                "endpointSelector": {"matchLabels": selector},
                "egressDeny": [{"toEntities": ["all"]}],
            },
        }
        await self.core_api.patch_namespaced_pod(
            pod_name,
            namespace,
            {"metadata": {"labels": selector}},
        )
        try:
            await self.custom_api.create_namespaced_custom_object(
                group="cilium.io",
                version="v2",
                namespace=namespace,
                plural="ciliumnetworkpolicies",
                body=body,
            )
        except ApiException as exc:
            if exc.status != 409:
                await self.core_api.patch_namespaced_pod(
                    pod_name,
                    namespace,
                    {"metadata": {"labels": {QUARANTINE_LABEL: None}}},
                )
                raise CloudWardError(
                    "KUBERNETES_ACTION_FAILED",
                    "Kubernetes rejected the typed Cilium quarantine",
                    status_code=502,
                    details={"status": exc.status},
                ) from exc
            state = await self.get_quarantine_policy_state(
                namespace, pod_name, policy_name=policy_name, quarantine_id=quarantine_id
            )
            if not state.enforced:
                raise CloudWardError(
                    "QUARANTINE_CONFLICT",
                    "An incompatible quarantine policy already exists",
                    status_code=409,
                ) from exc
        return QuarantinePolicyResult(
            namespace=namespace,
            pod_name=pod_name,
            policy_name=policy_name,
            quarantine_id=quarantine_id,
            applied=True,
        )

    async def get_quarantine_policy_state(
        self,
        namespace: str,
        pod_name: str,
        *,
        policy_name: str,
        quarantine_id: str,
    ) -> QuarantinePolicyState:
        self._require_namespace(namespace)
        _validate_name(pod_name, "pod name")
        _validate_name(policy_name, "policy name")
        _validate_name(quarantine_id, "quarantine id")
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_ACTION_UNAVAILABLE",
                "Cilium quarantine client is unavailable",
                status_code=503,
            )
        policy_exists = True
        policy: dict[str, Any] = {}
        try:
            policy = await self.custom_api.get_namespaced_custom_object(
                group="cilium.io",
                version="v2",
                namespace=namespace,
                plural="ciliumnetworkpolicies",
                name=policy_name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise CloudWardError(
                    "KUBERNETES_API_ERROR",
                    "Unable to read the Cilium quarantine policy",
                    status_code=502,
                    details={"status": exc.status},
                ) from exc
            policy_exists = False
        pod = await self.get_pod_health(namespace, pod_name)
        expected_selector = {QUARANTINE_LABEL: quarantine_id}
        spec = policy.get("spec", {}) if isinstance(policy, dict) else {}
        selector_matches = spec.get("endpointSelector", {}).get("matchLabels") == expected_selector
        deny_all = {"toEntities": ["all"]} in spec.get("egressDeny", [])
        return QuarantinePolicyState(
            namespace=namespace,
            pod_name=pod_name,
            policy_name=policy_name,
            policy_exists=policy_exists and selector_matches,
            target_label_matches=pod.labels.get(QUARANTINE_LABEL) == quarantine_id,
            deny_all_egress=deny_all,
        )

    async def remove_quarantine_policy(
        self,
        namespace: str,
        pod_name: str,
        *,
        policy_name: str,
        quarantine_id: str,
    ) -> QuarantinePolicyState:
        """Remove only the exact CloudWard policy and label recorded for this target."""

        self._require_namespace(namespace)
        _validate_name(pod_name, "pod name")
        _validate_name(policy_name, "policy name")
        _validate_name(quarantine_id, "quarantine id")
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_ACTION_UNAVAILABLE",
                "Cilium quarantine client is unavailable",
                status_code=503,
            )
        state = await self.get_quarantine_policy_state(
            namespace, pod_name, policy_name=policy_name, quarantine_id=quarantine_id
        )
        if state.policy_exists:
            try:
                await self.custom_api.delete_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=namespace,
                    plural="ciliumnetworkpolicies",
                    name=policy_name,
                    body=client.V1DeleteOptions(propagation_policy="Background"),
                )
            except ApiException as exc:
                if exc.status != 404:
                    raise CloudWardError(
                        "KUBERNETES_ACTION_FAILED",
                        "Kubernetes rejected removal of the recorded quarantine",
                        status_code=502,
                        details={"status": exc.status},
                    ) from exc
        await self.core_api.patch_namespaced_pod(
            pod_name,
            namespace,
            {"metadata": {"labels": {QUARANTINE_LABEL: None}}},
        )
        return await self.get_quarantine_policy_state(
            namespace, pod_name, policy_name=policy_name, quarantine_id=quarantine_id
        )

    async def create_typed_custom_object(
        self,
        *,
        namespace: str,
        group: str,
        version: str,
        plural: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a server-built custom resource in an allowed namespace."""

        self._require_namespace(namespace)
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_ACTION_UNAVAILABLE",
                "Custom Objects client is unavailable",
                status_code=503,
            )
        try:
            result = await self.custom_api.create_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                body=body,
            )
        except ApiException as exc:
            raise CloudWardError(
                "KUBERNETES_ACTION_FAILED",
                "Kubernetes rejected the typed custom resource",
                status_code=502,
                details={"status": exc.status, "resource": plural},
            ) from exc
        return result if isinstance(result, dict) else {}

    async def delete_typed_custom_object(
        self,
        *,
        namespace: str,
        name: str,
        group: str,
        version: str,
        plural: str,
    ) -> None:
        self._require_namespace(namespace)
        _validate_name(name, "custom resource name")
        if self.custom_api is None:
            raise CloudWardError(
                "KUBERNETES_ACTION_UNAVAILABLE",
                "Custom Objects client is unavailable",
                status_code=503,
            )
        try:
            await self.custom_api.delete_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
                body=client.V1DeleteOptions(propagation_policy="Background"),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise CloudWardError(
                    "KUBERNETES_ACTION_FAILED",
                    "Kubernetes rejected custom resource cleanup",
                    status_code=502,
                    details={"status": exc.status, "resource": plural},
                ) from exc

    @staticmethod
    def _pod_state(pod: Any) -> PodState:
        conditions = pod.status.conditions or []
        ready = any(
            condition.type == "Ready" and str(condition.status).lower() == "true"
            for condition in conditions
        )
        owners = pod.metadata.owner_references or []
        controller = next((owner for owner in owners if owner.controller), None)
        statuses = pod.status.container_statuses or []
        terminated = [
            status.last_state.terminated
            for status in statuses
            if status.last_state is not None and status.last_state.terminated is not None
        ]
        return PodState(
            namespace=pod.metadata.namespace,
            name=pod.metadata.name,
            phase=pod.status.phase or "Unknown",
            ready=ready,
            labels=dict(pod.metadata.labels or {}),
            controller_managed=controller is not None,
            controller_kind=controller.kind if controller else None,
            restart_count=sum(status.restart_count or 0 for status in statuses),
            termination_reasons=tuple(
                item.reason or "Unknown" for item in terminated
            ),
            exit_codes=tuple(item.exit_code for item in terminated),
        )
