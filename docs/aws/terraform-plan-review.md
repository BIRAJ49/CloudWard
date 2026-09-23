# Terraform plan review record

Create one copy of this record for every proposed apply. Do not reuse approval from an earlier plan.

## Plan identity

| Field | Value |
| --- | --- |
| Git commit | `<sha>` |
| Terraform version | `<version>` |
| Provider lockfile digest | `<sha256>` |
| Plan artifact digest | `<sha256>` |
| AWS account/region | `<account alias> / eu-north-1` |
| Generated at | `<UTC>` |
| Reviewer | `<identity>` |

## Required summary

1. **Creates:** list resource address/type and purpose. Attach the value-free workflow summary.
2. **Modifies:** state old intent, new intent, replacement/downtime risk, and why.
3. **Destroys:** list every destroy/replacement. Any surprise stops the apply.
4. **IAM/security:** roles, policies, trust-policy changes, EKS access entries, encryption, and privilege expansion/reduction.
5. **Networking:** VPC/subnet/routes, EKS endpoint CIDRs, security-group ingress/egress, DNS, ALB, and public IPv4 changes.
6. **Cost impact:** EKS, EC2/Spot, EBS, ALB, public IPv4, transfer, logs, S3, and any newly introduced fixed hourly service.
7. **Public exposure:** exact ports, protocols, sources, endpoints, and whether Cloudflare/Gateway policy protects them.
8. **Data/state:** state moves, storage replacement, backup status, retention, and sensitive output risk.
9. **Rollback:** configuration revert, workload/GitOps rollback, infrastructure re-plan, and any non-reversible data action.
10. **Operational readiness:** owner, monitoring, budget alert, teardown window, and evidence-capture location.

## Approval decision

```text
Decision: APPROVE | REJECT
Approved plan SHA-256:
Approved commit:
Approval scope:
Expiry:
Conditions:
```

Approval authorizes only the exact plan digest and commit. It does not authorize later plans, IAM additions, production deploys, a destroy, or removal of the state backend.
