# Part 2 local platform architecture

Part 2 adds a local reliability telemetry plane and a controlled chaos runtime without changing the Part 1 control-plane authority model.

```text
cloudward-staging workloads
  ├─ /metrics ───────────────────────────► Prometheus
  ├─ OTLP traces ─► OTel Collector ──────► Tempo
  └─ JSON container logs ─► OTel Collector ─► Loki

Prometheus ─► Alertmanager ── Bearer-authenticated webhook ─► CloudWard API

Grafana ─► Prometheus + Loki + Tempo

CloudWard typed scenario ─► OPA/Kyverno ─► Chaos Mesh ─► labelled staging target
```

## Pinned local components

| Component | Helm chart | Pinned chart version | Local topology |
| --- | --- | ---: | --- |
| Prometheus, Alertmanager, Grafana | `prometheus-community/kube-prometheus-stack` | `88.5.3` | one replica each |
| Loki | `grafana-community/loki` | `18.11.0` | one monolithic process plus gateway |
| Tempo | `grafana-community/tempo` | `2.2.4` | one local-storage process |
| OpenTelemetry Collector | `open-telemetry/opentelemetry-collector` | `0.170.0` | DaemonSet, contrib image `0.158.0` |
| Chaos Mesh | `chaos-mesh/chaos-mesh` | `2.8.4` | one controller plus one daemon per node |

Versions are constants in `scripts/lib.sh`; install commands never use an unpinned chart version.

## Namespace and trust boundaries

- `observability` contains telemetry infrastructure and is explicitly excluded from chaos.
- `chaos-mesh` contains trusted Chaos Mesh controllers/daemons and is excluded from chaos.
- `cloudward-staging` is the only namespace annotated for Chaos Mesh injection.
- `cloudward-production`, `kube-system`, `argocd`, `observability`, `kyverno`, `tetragon`, and `chaos-mesh` are not opted in.
- Kyverno admits the supported `StressChaos` and `PodChaos` resources only when both the resource namespace and the sole selector namespace are `cloudward-staging`, and the selector contains `cloudward.io/demo-target: "true"`.
- The Chaos Mesh dashboard is disabled. It would be a second launch path outside CloudWard's RBAC, typed scenario registry, OPA decision, and audit trail.

Chaos Mesh's node daemon is necessarily privileged and can access the k3s containerd socket. That exception exists only in the dedicated namespace and is not inherited by application workloads.

## Telemetry routing

Prometheus Operator discovers ServiceMonitors, PodMonitors, and PrometheusRules across namespaces. The CloudWard demo ServiceMonitor selects the GitOps-managed service in `cloudward-staging`, adds bounded target metadata, scrapes every 15 seconds, and applies target/sample/label limits.

The OpenTelemetry Collector runs once per node. It accepts OTLP/gRPC and OTLP/HTTP, tails Kubernetes container logs, adds Kubernetes resource attributes, batches with a memory limiter, exports traces to Tempo, and exports logs through Loki's native OTLP endpoint. Collector logs are excluded from its file-log receiver to avoid a self-ingestion loop.

The collector drops spans for `/metrics`, `/health/live`, and `/health/ready`. These endpoints remain observable through metrics and logs but do not create repetitive trace noise.

## Correlation model

Applications retain `trace_id` and `span_id` as structured JSON fields, never Loki stream labels. Grafana provisions:

- a Loki derived field that opens a matching Tempo trace;
- Tempo-to-Loki navigation constrained by service and environment resource attributes;
- Tempo-to-Prometheus navigation using the stable `service` dimension.

This avoids high-cardinality Prometheus labels and Loki streams while keeping identifiers searchable. The validation script requires a Tempo trace and a Loki record containing the same trace ID before reporting correlation success.

## Retention and storage truth

Prometheus, Loki, and Tempo are configured for a logical seven-day window. Prometheus and Loki each have an 8 GiB local `emptyDir` bound; Tempo uses local ephemeral storage. The k3d cluster intentionally disables the k3s local-storage provisioner, so telemetry does not survive pod or cluster recreation. Seven days is a compaction/query policy and portfolio target, not a durability guarantee.

This topology is intentionally unsuitable for production. Production would require durable object/block storage, capacity planning, high availability, tenant authentication, backup/restore, and longer alert windows.
