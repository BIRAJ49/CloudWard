# AWS disaster recovery

CloudWard v1 has one EC2 control plane, co-located PostgreSQL, one EKS cluster, and no multi-region failover. Recovery is operator-driven. Recovery-time and recovery-point objectives are not guaranteed until measured with real drills.

## Recovery priorities

1. Stop unsafe automation and preserve audit/state evidence.
2. Restore identity, policy, and GitOps control before resuming actions.
3. Restore PostgreSQL before treating incident history as complete.
4. Reconcile desired Kubernetes state from Git.
5. Validate telemetry and typed execution before enabling automation.

## Failure procedures

| Failure | Recovery | Data/risk notes |
| --- | --- | --- |
| EC2 control plane | Use Terraform to replace the instance from reviewed configuration; attach only approved restored data; recreate the `cloudward-eks` kube context with the instance role; restore origin TLS and `.env.production` from the secret custodian; restore PostgreSQL; start Compose and validate readiness/RBAC. | Service unavailable during recovery. Local EBS loss can lose changes after the last backup. Never bake secrets into AMIs/user data/state. |
| PostgreSQL corruption/loss | Stop API/worker, preserve the failed volume/dump, restore the newest verified custom dump, run migrations only if compatible, check incident/audit referential integrity, then resume workers. | RPO equals last valid backup. Redis results do not reconstruct the authoritative audit trail. |
| Redis loss | Recreate Redis and restart workers after PostgreSQL is healthy. Reconcile durable incident/task state before manually requeuing safe idempotent work. | In-flight tasks and ephemeral result/cache data may be lost. Never assume an action did not execute; inspect audit and target state. |
| Argo CD loss | Reinstall the pinned controller, restore approved repository credentials, and apply root apps. Let Argo reconcile from Git; compare live drift before pruning. | Cluster workloads may continue while management is unavailable. Git is authoritative only for resources actually managed there. |
| EKS worker loss | Managed node group/Karpenter should replace capacity. Confirm AWS VPC CNI, Cilium chaining, storage attachment, PDBs, and stable placement for critical controllers. | Single-replica system components can be temporarily unavailable. Spot interruption is expected for demo workloads. |
| Entire EKS cluster loss | Produce a reviewed Terraform replacement plan, recreate infrastructure, bootstrap platform controllers, restore GitOps apps, secrets, then validate admission/network/telemetry before incidents. | In-cluster telemetry and unexported data are lost. One-cluster namespace separation is not disaster isolation. |
| Terraform state loss/lock | Stop all Terraform writers. Recover a known S3 version, preserve the current object and lockfile for investigation, verify serial/lineage, run refresh-only/read-only inspection, then plan. | State can contain sensitive values. Never delete a lock unless ownership and inactivity are proven. |
| GitHub App key compromise | Disable/revoke the key, suspend automation, audit installation tokens/actions and write paths, generate a new key, store it only in approved secret locations, and re-enable after bounded tests. | Assume attempted repository writes; review branches, Issues, PRs, webhooks, and audit dedupe records. |
| OpenRouter outage/compromise | Disable AI diagnosis, rotate credentials if needed, retain deterministic runbooks/risk/OPA, and audit model interactions. | Reliability/security flows must continue without AI; quality of supplemental diagnosis is reduced. |
| Cloudflare outage/misconfiguration | Keep the origin restricted; do not open the EC2 security group to the world as a shortcut. Repair DNS/proxy/origin certificates or use an explicitly approved private operator path. | Public UI is unavailable. Direct origin bypass would remove a trust boundary. |

## Backup schedule and drill evidence

Choose a documented schedule appropriate to the demo window; at minimum take a backup before infrastructure changes and before teardown. Retain the dump encrypted outside the instance if recovery after instance loss matters. A successful `pg_dump` exit is not a restore test. Record backup checksum, restore target, duration, migration version, row-count/integrity checks, and redacted health evidence.

Terraform state versions, Git repositories, signed image/SBOM attestations, and PostgreSQL dumps are separate recovery assets. None alone restores the whole system.
