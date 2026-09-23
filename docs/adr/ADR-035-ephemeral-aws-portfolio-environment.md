# ADR-035: Treat AWS as an ephemeral portfolio environment

Status: Accepted

## Context

An always-on EKS control plane plus EC2, EBS, ALB, public IPv4, logs, and transfer cannot honestly be guaranteed under an approximate USD 50 monthly target.

## Decision

Local k3d remains the daily environment. AWS is created for bounded real-cloud validation and portfolio evidence, with an owner, planned lifetime, AWS Budget alerts, Karpenter limits, small storage/retention, no NAT Gateway, and a reviewed teardown. Two public-egress and two isolated subnets span two Availability Zones; the cost tradeoff is documented rather than presented as ideal private egress.

## Consequences

AWS evidence is real only while deployed and validated; repository definitions are not proof. Budget alerts do not cap spend. Frequent creation/teardown increases operational work and requires disciplined state, GitOps load-balancer cleanup, backups, and explicit destructive approval.
