# Chaos Mesh safety and reference scenarios

Chaos Mesh is installed only in local k3d for controlled reliability experiments. CloudWard does not accept arbitrary Chaos Mesh YAML from a user.

## Enforcement layers

1. The backend scenario registry accepts fixed scenario IDs and produces typed resources.
2. RBAC limits scenario launch to Operator and Admin roles.
3. OPA evaluates the requested target and action.
4. `controllerManager.enableFilterNamespace=true` makes Chaos Mesh ignore namespaces that have not opted in.
5. Only `cloudward-staging` has `chaos-mesh.org/inject=enabled`.
6. Kyverno requires the exact staging namespace and `cloudward.io/demo-target=true` selector on supported Chaos resources.

UI restrictions are not security controls. Cluster-admin access can always exceed application RBAC and must remain an administrative capability.

## Reference resources

The repository contains fixed, bounded reference manifests for platform integration and backend parity:

| Scenario | Resource | Scope | Duration | Expected signal |
| --- | --- | --- | ---: | --- |
| R2 CPU saturation | `StressChaos` | every labelled demo replica | 90s | `HighCPUSaturation` |
| R3 memory pressure | `StressChaos` | one labelled demo replica | 90s | memory pressure and, if the configured limit is crossed, `ContainerOOMKilled` |
| R4 workload failure | `PodChaos` / `pod-kill` | one labelled demo replica | 30s | `WorkloadUnavailable`, followed by Kubernetes reconciliation |

These manifests live under `k8s/chaos-mesh/scenarios/`. They contain no template for an arbitrary namespace, selector, stress size, or command. R1 bad deployment is a deterministic release state, not a Chaos Mesh experiment.

R4 is explicitly a workload failure. It is not represented as a real node failure because a safe single-host k3d demonstration cannot prove node replacement semantics. Its expected resolution source is `PLATFORM_SELF_HEALING` when Kubernetes restores the replica without a CloudWard action.

## Forbidden targets

Chaos must never target `cloudward-production`, `kube-system`, `argocd`, `observability`, `kyverno`, `tetragon`, or `chaos-mesh`. An unlabeled staging workload is also forbidden. Static Kyverno fixtures cover production, mixed-namespace, and unlabeled selectors.

## Cleanup

Every scenario has a short `duration`, but the orchestrator must still delete its resource in a `finally` path and wait for the target to recover. Emergency cleanup is explicit and narrow:

```bash
kubectl -n cloudward-staging delete stresschaos cloudward-r2-cpu-saturation --ignore-not-found
kubectl -n cloudward-staging delete stresschaos cloudward-r3-memory-pressure --ignore-not-found
kubectl -n cloudward-staging delete podchaos cloudward-r4-workload-failure --ignore-not-found
```

Never use a namespace-wide wildcard deletion as scenario cleanup.
