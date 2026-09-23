# ADR-031: Bounded Karpenter with Spot restricted to non-critical workloads

Status: Accepted

## Context

Real dynamic capacity demonstrates EKS FinOps, but unbounded provisioning and Spot-only critical services create cost and availability hazards.

## Decision

A minimal managed On-Demand system node group bootstraps essential controllers. Current Karpenter `NodePool`/`EC2NodeClass` APIs provide a bounded critical On-Demand class and a bounded stateless demo class that prefers Spot with On-Demand fallback. Allowed architectures, families, capacity types, CPU/memory totals, disruption, and consolidation are explicit. PostgreSQL, CloudWard, Argo/Kyverno essentials, and recovery controllers are never Spot-only.

## Consequences

The platform can demonstrate provisioning and consolidation without confusing Karpenter actions with CloudWard remediation. Spot interruption remains expected, and limits can intentionally leave a workload pending instead of creating an unexpectedly large instance.
