# ADR-036: Separate OPA decision authority from Kyverno admission

Status: Accepted

## Context

CloudWard needs to decide whether an incident action is authorized and independently prevent unsafe Kubernetes resources from entering the cluster. Treating either policy engine as a universal replacement would blur inputs, lifecycle, and failure behavior.

## Decision

OPA is the final authority for CloudWard remediation/containment decisions after deterministic risk and approval binding. Kyverno controls Kubernetes admission, including namespace safety, immutable digests, and Cosign identity. IAM and Kubernetes RBAC remain lower-level permission ceilings. AI supplies no policy authority.

## Consequences

Defense in depth catches both unsafe decisions and unsafe manifests, but policy ownership and tests exist in two systems. A request may be allowed by OPA and then rejected by Kyverno; CloudWard must record that real outcome and roll back or escalate rather than bypass admission.
