# ADR-012: Attribute Kubernetes self-healing separately

- Status: Accepted
- Date: 2026-08-22

## Context

Kubernetes controllers may restore a failed pod or replica without a CloudWard remediation. Claiming that recovery as an autonomous CloudWard action would make the audit record misleading.

## Decision

Record a distinct `PLATFORM_SELF_HEALING` resolution source when Kubernetes reconciles the workload and CloudWard only detects, observes, and verifies recovery. An audit trail must explicitly show that no CloudWard action execution occurred.

## Consequences

The product reports operational value truthfully and distinguishes detection/verification from action. Scenario R4 can demonstrate platform reconciliation without pretending that local k3d reproduces cloud node replacement.
