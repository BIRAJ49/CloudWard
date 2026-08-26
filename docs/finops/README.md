# Deterministic FinOps

CloudWard Part 3 installs the pinned OpenCost Helm chart in the local `opencost` namespace and points it at the existing Prometheus service. `scripts/port-forward-telemetry.sh` exposes OpenCost only on loopback port `9003`, allowing the Compose API to use `http://host.docker.internal:9003` without exposing OpenCost to the network.

The F1 workload uses the controlled `cloudward-demo` staging deployment. Its local requests are intentionally generous enough to create an observable rightsizing exercise. CloudWard never substitutes example utilization values: it reads per-pod CPU and memory samples from Prometheus, current requests and limits from kube-state-metrics, and allocation cost from OpenCost.

For F1, the engine computes p50/p95/p99 and proposes each request as the larger of observed p95 times configured headroom or the configured minimum. It refuses short, sparse, missing, unsafe, or insignificant reductions. Monetary impact is emitted only when OpenCost supplies CPU and RAM cost components. Local OpenCost output is explicitly not represented as AWS savings.

F2 compares allocatable capacity, scheduled requests, observed p95 use, pod count, and local allocation. It produces an advisory capacity-strategy recommendation only when both configured utilization thresholds are met. It never changes node count and does not invent a monetary estimate without topology and price evidence.

Persistent resource changes use a draft GitHub pull request against one configured repository and the fixed staging values path. The handler re-reads that file at the supplied base commit, compares its CPU and memory requests with the evidence-bound current state, applies only the two typed request fields, and passes the blob SHA to GitHub for optimistic concurrency. CloudWard never merges the PR or resizes a production Deployment directly; GitHub review is authoritative.

The dashboard approval queue is authoritative only for runtime operational actions. Each approval is bound to an incident, proposal version, target, expected state digest, policy decision, risk, and expiry. Decision rows are locked transactionally. Before approval, CloudWard rechecks incident state, execution history, target replicas/image, policy, role, and expiry. A stale proposal is invalidated instead of executed.
