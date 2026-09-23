# Outbound cluster evidence agent

The agent is a read-only extension of the existing control plane, not a second executor. It makes live inventory and incident evidence available through outbound HTTPS without publishing telemetry services on the internet. It does **not** replace the live Kubernetes/telemetry access needed by the existing action verifier, nor grant authority to cached observations.

## Data flow

1. The operator registers a cluster and services in CloudWard and configures a dedicated agent identity bound to the cluster UUID.
2. The in-cluster process reads only named Deployments and bounded, label-selected Pods in the configured staging/production namespaces.
3. Fixed, bounded Prometheus, Loki, Tempo, and OpenCost queries gather supporting evidence. Failed providers are explicitly listed; missing data is never represented as a healthy check.
4. A report with a UUID, source timestamp, and registered target identities is sent to `POST /api/v1/agent/reports` over HTTPS.
5. The API authenticates before buffering, enforces a 512 KiB body limit, rejects stale/future/out-of-order reports and unknown targets, redacts again, and stores one latest observation per cluster.
6. Active incidents for those exact cluster/service identities receive evidence at most once per minute. Resolved incidents, actions, approvals, policies, and incident state are not modified.
7. SSE notifies the existing inventory and incident pages. Inventory derives `CONNECTED`, `DEGRADED`, or `STALE` from the timestamp. `CONNECTED` means recent agent visibility, not that all workloads are healthy.

Ordinary Viewer-or-higher RBAC permits `GET /api/v1/agent/clusters/{cluster_id}`; an agent token grants no dashboard, worker, action, or approval permission. This v1 identity supports one configured cluster. Multi-cluster token management is not implied.

## Configuration and deployment

No commands below were executed against a real cluster or registry during implementation. Review and explicitly authorize deployment/publication separately.

1. Upgrade the backend to Alembic head through the normal migration process. Revision `52a7c9d1e402` adds the agent state table; the following `64b9e0a3f215` corrects historical schema drift and legacy FinOps enum casing. Neither deletes incident/audit data. Both were validated on isolated local PostgreSQL, not your application database.
2. Read the registered cluster UUID from authenticated `GET /api/v1/clusters`. Targets must exactly match registered `Service.namespace`, `Service.name`, and `Service.deployment_name`; reports cannot create inventory or change criticality/labels.
3. Generate a random token of at least 32 characters outside Git. Configure only the API with `CLUSTER_AGENT_ENABLED=true`, `CLUSTER_AGENT_CLUSTER_ID`, and `CLUSTER_AGENT_TOKEN`. Do not reuse the worker/webhook/session token. API intake is disabled by default.
4. Store that token in an existing Kubernetes Secret named by Helm `existingSecret`, with key `token`. Use your approved secret-delivery procedure, not a committed values file or command-line token argument.
5. Review `helm/cloudward-agent/values.yaml`. Set `enabled`, the real cluster UUID, HTTPS public control-plane origin, registered targets, actual telemetry Service addresses, and the verified API image digest. The agent uses the same application image with a different Python entrypoint; it does not start FastAPI or connect to the database.
6. Supply restricted `controlPlaneCIDRs` and `kubernetesApiCIDRs`. The first must cover the approved HTTPS destination (Cloudflare proxy addresses if applicable); the second must cover the actual Kubernetes API endpoints as enforced by the deployed CNI. Do not use `0.0.0.0/0` or `::/0`. DNS and the four telemetry ports are separately scoped to their namespaces. Validate EKS/Cilium DNAT behavior before enabling.
7. The opt-in Argo CD Application is `cloudward-gitops/apps/aws/cluster-agent.yaml`. It is disabled and manually synced by default. Review its configuration in Git before first sync. The chart renders a Deployment, projected service-account token, namespaced Roles/RoleBindings, and a deny-ingress/restricted-egress NetworkPolicy; no Service, public route, or cluster-admin binding is created.
8. Allow authenticated machine requests to the intake path through your Cloudflare configuration without an interactive browser challenge. Do not remove API token verification or origin TLS/authenticated origin pulls.

Defaults: one replica, 30-second collection interval, at most four explicit targets, 50 Pods per target, five telemetry records with up to five samples each, five-minute telemetry window, eight-second provider deadline, three delivery attempts, and 180-second freshness. Pod-list truncation is recorded, not hidden. Token rotation reads the projected Kubernetes token per request. Rotate the CloudWard token with a coordinated API/Secret rollout; API rotation immediately invalidates the old token.

The Deployment is non-root, read-only, drops all capabilities, and has bounded requests/limits and a 1 MiB writable state volume. It reads no Kubernetes Secrets, pod environments, annotations, or log files. Kubernetes RBAC cannot restrict pod `list` by a label selector, so a compromised service account can list Pod metadata within its explicitly bound namespaces; it still cannot exec, mutate, or list Secrets.

Readiness requires a recent acknowledged delivery; liveness checks loop progress so a temporary API outage does not deliberately restart an otherwise functioning agent. Retries preserve the report ID. A lost acknowledgement therefore does not duplicate incident evidence. Old report replay cannot overwrite a newer observation.

## Integration boundaries

- **Environment isolation:** metrics include the Kubernetes namespace and service label; traces require both service and `k8s.namespace.name`. The existing collector enriches traces with Kubernetes attributes. Missing namespace attributes yield no matching traces, not an unscoped fallback. Namespace-wide restart counts are supporting context, not proof that a specific deployment is failing. See the upstream [TraceQL filter documentation](https://grafana.com/docs/tempo/latest/traceql/construct-traceql-queries/). Internal telemetry requests ignore inherited HTTP proxy variables.
- **Security events:** the existing Tetragon DaemonSet/forwarder remains the signed security-event path, with its own credential and schema. The read-only inventory agent does not request host mounts, eBPF capabilities, or turn log samples into authoritative security events.
- **Remediation:** existing typed executors still require live evidence, deterministic risk, OPA, approval where required, and objective verification. A compromised agent identity can poison advisory evidence, not authorize execution. Keep agent evidence marked untrusted in AI inputs.
- **FinOps:** reported OpenCost allocation is evidence, not a savings claim or an automatic resize. Existing FinOps analysis/PR generation still performs its bounded utilization and policy checks.
- **Telemetry bridge:** periodic agent evidence works without it; existing on-demand diagnosis/verification/FinOps queries still need private direct telemetry access or the documented bridge. A queued outbound RPC replacement is a separate remaining capability, not silently claimed here.
- **Storage:** only the newest standalone observation is retained. Incident-linked evidence and status-change audit records remain append-oriented. Up to 20 most-recent active incidents per target are enriched per report; larger incident fleets need a pagination/backfill policy.

## Validation and troubleshooting

Run backend tests in `tests/api/test_cluster_agent.py`, `tests/unit/test_cluster_agent_runtime.py`, and `tests/unit/test_agent_chart.py`. They cover collection→delivery→intake→persistence→RBAC reads using local test transports, identity isolation, secret redaction, idempotency, clock skew, size limits, rate control, unavailable providers, bounded retries, and rendered Kubernetes permissions. This is not evidence of a live EKS deployment.

- `AGENT_AUTHENTICATION_FAILED`: inspect API/Secret token alignment; do not print either token.
- `AGENT_CLUSTER_DENIED` / `AGENT_TARGET_DENIED`: correct registration and identity, not RBAC bypasses.
- `AGENT_REPORT_STALE`: fix node/control-plane clocks or connectivity; do not disable freshness checks.
- `DEGRADED`: inspect named collection error codes, service DNS, and namespace-scoped read permissions.
- `STALE`: last observation exceeded freshness; investigate the pod, delivery, TLS, or network policy.
- Missing incident evidence: the incident must be active and reference the same registered cluster and service IDs; the one-minute evidence sampling limit is intentional.
