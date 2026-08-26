# ADR-011: Chaos Mesh for controlled local reliability testing

- Status: Accepted
- Date: 2026-08-22

## Context

CloudWard needs reproducible CPU, memory, and workload disruption signals in local k3d without unsafe host exhaustion or arbitrary user-supplied commands.

## Decision

Use pinned Chaos Mesh in the local cluster. Permit only typed scenario definitions against `cloudward-staging` workloads labelled `cloudward.io/demo-target=true`. Enforce the target through backend validation, OPA, namespace opt-in, and Kyverno. Disable the direct Chaos Mesh dashboard so CloudWard remains the supported launch and audit surface.

## Consequences

Experiments produce real Kubernetes/runtime behavior and have bounded duration and cleanup. The node daemon requires a privileged, container-runtime-aware exception in its isolated namespace. These experiments remain local-only and do not imply production authorization.
