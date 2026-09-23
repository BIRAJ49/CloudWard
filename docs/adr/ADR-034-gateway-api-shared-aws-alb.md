# ADR-034: Gateway API through one shared AWS ALB

Status: Accepted

## Context

The demo needs real public AWS ingress without one load balancer per service. Cilium Gateway behavior is not assumed compatible with the selected chaining mode.

## Decision

The AWS Load Balancer Controller uses its supported Gateway API integration to provision one shared public ALB. `Gateway` and `HTTPRoute` expose only selected demo services. PostgreSQL, Redis, OPA, workers, telemetry stores, Tetragon, and internal simulators have no public route. Images stay in GHCR; ECR is not introduced.

## Consequences

Gateway API keeps routing declarative and portable at the API level, while annotations/controller behavior remain AWS-specific. The ALB is a fixed cost and shared blast radius. Kubernetes-owned ALB resources must be removed and observed gone before Terraform teardown.
