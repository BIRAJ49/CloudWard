# Local observability

CloudWard's local observability plane is installed by `scripts/install-part2-platform.sh`. It provisions Prometheus, Alertmanager, Grafana, Loki, Tempo, and an OpenTelemetry Collector in `observability`.

## Install

Set the same non-placeholder token used by the backend in `.env`:

```text
ALERTMANAGER_WEBHOOK_TOKEN=<at-least-32-random-characters>
```

Then use the normal cluster bootstrap, or install Part 2 into an already bootstrapped `k3d-cloudward` context:

```bash
./scripts/install-part2-platform.sh
```

The installer refuses any other Kubernetes context. It creates Kubernetes Secrets from local environment values and never writes their values to source files. A Grafana password is generated when no existing secret or `CLOUDWARD_GRAFANA_ADMIN_PASSWORD` is supplied.

Retrieve the local Grafana credentials without putting them in shell history:

```bash
kubectl -n observability get secret cloudward-grafana-admin \
  -o jsonpath='{.data.admin-user}' | base64 --decode
kubectl -n observability get secret cloudward-grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 --decode
```

## Access

All services remain ClusterIP-only. Forward one explicitly:

```bash
./scripts/port-forward-observability.sh grafana       # http://127.0.0.1:3001
./scripts/port-forward-observability.sh prometheus    # http://127.0.0.1:9090
./scripts/port-forward-observability.sh alertmanager  # http://127.0.0.1:9093
./scripts/port-forward-observability.sh loki          # http://127.0.0.1:3100
./scripts/port-forward-observability.sh tempo         # http://127.0.0.1:3200
```

When the CloudWard API is running in Docker Compose, keep the three telemetry
stores bridged to its configured `host.docker.internal` endpoints in a separate
terminal:

```bash
make telemetry-bridge
```

Grafana automatically provisions Prometheus, Loki, and Tempo plus four dashboards:

- CloudWard Demo Service;
- CloudWard Reliability Overview;
- Kubernetes Workload Health;
- CloudWard Control Plane.

Panels query real telemetry. A missing metric remains `No data`; dashboards do not synthesize a value.

## Alert pipeline

`PrometheusRule` resources define the four canonical local reliability alerts:

| Alert | Sustained condition | Runbook label |
| --- | --- | --- |
| `HighHTTPErrorRate` | more than 20% HTTP 5xx with a request-rate floor for 1 minute | `reliability.bad-deployment` |
| `HighCPUSaturation` | demo pod CPU above 85% of its request for 2 minutes | `reliability.cpu-saturation` |
| `ContainerOOMKilled` | OOM termination plus a recent restart | `reliability.memory-pressure` |
| `WorkloadUnavailable` | an allowlisted staging Deployment lacks replicas for 45 seconds | `reliability.platform-self-healing` |

Demo intervals are intentionally short. Production should use SLO burn rates, materially longer windows, traffic floors, and environment-specific routing.

Alertmanager groups by stable alert, service, namespace, and environment fields. It sends firing and resolved events through the local gateway at `http://host.k3d.internal:8080/api/v1/webhooks/alertmanager` with a Bearer credential loaded from `cloudward-alertmanager-webhook`. Alerts are evidence; neither annotations nor labels become executable commands.

Platform alerts for CloudWard API, worker, webhook errors, remediation failures, and OPA availability are labelled `cloudward_self_remediation=disabled`. They notify; they do not create a loop in which CloudWard tries to repair itself.

## Retention and resource limits

All telemetry stores use a seven-day logical policy. Prometheus and Loki have 8 GiB local bounds; Tempo is ephemeral. Every installed component has CPU and memory requests/limits in its values file. Cache and distributed modes that add unnecessary local processes are disabled.

## Validate when runtime data exists

After the instrumented demo has served requests and the control plane is running:

```bash
./scripts/validate-part2-platform.sh
```

The script checks release/controller health, Prometheus demo scraping, Loki staging logs, Tempo trace presence, and a shared trace ID in Tempo and Loki. A missing runtime signal fails the check; it is not treated as a pass.

## Cleanup

The normal named-cluster destroy path removes the stack:

```bash
make cluster-destroy
```

Do not manually delete broad namespaces or unrelated clusters.
