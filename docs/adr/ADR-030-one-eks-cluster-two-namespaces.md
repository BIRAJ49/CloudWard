# ADR-030: One EKS cluster with staging and production namespaces

Status: Accepted

## Context

Separate clusters/accounts provide stronger isolation but materially increase fixed EKS cost for a portfolio environment.

## Decision

CloudWard v1 uses one EKS cluster, `cloudward-aws-eu-north-1`, with `cloudward-staging` and `cloudward-production` namespaces. RBAC, Kyverno, Cilium, Argo projects/applications, target labels, risk, OPA, and promotion PRs enforce the logical boundary. Incident Lab and destructive chaos remain staging-only.

## Consequences

The design is reproducible and cheaper, but namespace separation is not a security or failure boundary equivalent to separate clusters/accounts. Cluster-wide failure and privileged controller compromise can affect both environments; the limitation is public and intentional.
