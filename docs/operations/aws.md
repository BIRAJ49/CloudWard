# AWS operations guide

CloudWard v1 is not highly available. Prefer GitOps reconciliation and typed CloudWard actions over ad-hoc mutation. Record the target AWS account, region, kube context, incident ID, correlation ID, and UTC time before intervention.

## Start and health

On the intended EC2 host, inspect configuration before starting:

```bash
cd /opt/cloudward
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml config
sudo systemctl start cloudward-compose
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml ps
```

Check `/health/live` and `/health/ready` through the Cloudflare hostname, then confirm the origin cannot be reached without Cloudflare's authenticated-origin-pull certificate. Inspect container logs with bounded time ranges; redact secrets before sharing. `ready` failure means unavailable, not healthy with a warning.

## EKS access

The EC2 instance role creates the context without static AWS keys:

```bash
aws eks update-kubeconfig \
  --region eu-north-1 \
  --name cloudward-aws-eu-north-1 \
  --alias cloudward-eks \
  --kubeconfig /opt/cloudward/.aws/cloudward-kubeconfig
kubectl --kubeconfig /opt/cloudward/.aws/cloudward-kubeconfig --context cloudward-eks auth can-i --list
```

The production API mounts this file read-only and uses `cloudward-eks`. The image must contain the AWS credential helper used by the kubeconfig. Authentication comes from the EC2 instance profile; do not put access keys in the environment or file.

The production-specific API and worker images extend the ordinary images only with Debian's signed, version-pinned AWS CLI v2 package. Builds reject unsupported architectures and assert the installed v2 version; runtime still uses the existing non-root users. Build their base image references from immutable digests in CI. The EC2 metadata service requires tokens and a hop limit of two so AWS CLI inside bridged containers can receive instance-role credentials. That hop-limit expansion is a deliberate residual risk: run only trusted control-plane containers, keep IMDSv2 required, constrain their networks and outbound access, and treat SSRF prevention as part of the security boundary.

The supervised telemetry bridge uses the same instance-role exec-auth context with `EXPECTED_KUBE_CONTEXT=cloudward-eks`. Every `kubectl port-forward` binds `127.0.0.1`; Compose reaches it through `host.docker.internal`. Never publish Prometheus, Loki, Tempo, or OpenCost on the EC2 security group. Start it after EKS and platform services are healthy:

```bash
sudo systemctl start cloudward-telemetry-bridge
sudo systemctl status cloudward-telemetry-bridge
```

## GitOps recovery and Argo CD

1. Check repository availability and the exact desired commit/digest.
2. Inspect Application conditions, sync status, health, repository credentials, and controller logs.
3. Resolve signature/admission/Helm errors in Git, then let Argo retry. Do not patch production desired state directly.
4. If Argo is lost, reinstall its pinned bootstrap release, restore repository credentials from the approved secret source, and reapply only the root Application/ApplicationSet manifests. Git remains the workload source of truth.
5. Never resolve drift by deleting audit evidence or weakening Kyverno/OPA.

Useful read-only checks:

```bash
kubectl --context cloudward-eks get applications -A
kubectl --context cloudward-eks get events -A --sort-by=.metadata.creationTimestamp
kubectl --context cloudward-eks get deploy,pod -n cloudward-staging
kubectl --context cloudward-eks get deploy,pod -n cloudward-production
```

## Karpenter

Check controller health, `NodePool`, `EC2NodeClass`, `NodeClaim`, pod scheduling events, instance-type constraints, and CPU/memory limits. Critical components must remain on stable system/On-Demand capacity. For Spot interruption or failed launch, confirm On-Demand fallback is permitted before changing constraints. Do not remove bounds merely to make a demo schedule.

## Cilium and networking

Confirm AWS VPC CNI is healthy before diagnosing Cilium. On AWS, Cilium must report chaining, not replacement-CNI mode. Check agents, DNS, endpoint policy state, pod-to-pod/service traffic, and the specific quarantine policy. Preserve an emergency management path before changing network policy. A Helm release alone is not health evidence.

## Tetragon

Inspect DaemonSet coverage, kernel/support messages, policy load state, forwarder authentication, replay/rate-limit rejection, and a bounded known-safe test event. If the node kernel changes, revalidate policy behavior. Never use real malware or host compromise as a test.

## Observability and OpenCost

Check scrape targets and recording rules first, then Alertmanager routing, OpenTelemetry export, Loki/Tempo ingestion, Grafana data sources, PVC utilization, and seven-day retention. OpenCost recommendations require a sufficient observation window and matching Prometheus samples. Missing/stale data blocks a recommendation; it is not zero cost.

## PostgreSQL backup and restore

Run `scripts/aws/postgres-backup.sh` from an authorized root session. It writes a private custom-format dump under `/var/backups/cloudward/postgres` and does not delete older backups. Copy backups to an approved encrypted location according to the operator's retention policy and test restoration periodically.

A restore replaces database contents and stops API/worker processing. Review the dump, maintenance window, and rollback, then use the explicit confirmation described by `scripts/aws/postgres-restore.sh`. After restore, run readiness, migration compatibility, incident/audit integrity, and login checks. Redis loss may drop transient queues/results but must not rewrite PostgreSQL history.

## Celery

Check Redis first, then worker heartbeat, queue depth, task correlation IDs, retry count, and dead/failed tasks. At three failed automatic remediation attempts the incident must escalate; do not replay it indefinitely. Before requeuing, prove the task is idempotent and the target/approval is still current.

## OpenRouter failure mode

Provider errors, invalid schemas, timeouts, and circuit-open state degrade to deterministic behavior. Confirm redaction, selected/fallback model metadata, request limits, and `AI_UNAVAILABLE` audit records. Never bypass risk or OPA because AI is down. Disable diagnosis and rotate the key if exposure is suspected.

## GitHub integration failure

Check App installation scope, private-key age, installation-token exchange, repository/path allowlists, branch protection, rate limits, and deduplication records. Do not substitute a PAT. A failed Issue/PR is tracked and retried within bounds; it does not authorize direct production mutation.

## Teams failure

Check the workflow URL outside logs, HTTP status, timeout/retry audit, event configuration, and redacted payload. Teams is notification-only; an outage must not change incident policy or remediation state. Rotate the URL if it appears in logs or screenshots.
