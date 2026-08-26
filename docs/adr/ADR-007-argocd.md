# ADR-007: Argo CD for GitOps reconciliation

- Status: Accepted
- Date: 2026-08-13

## Context

Normal deployment through ad hoc commands would obscure desired state and undermine the future persistent-remediation model.

## Decision

Store demo workload desired state as a Helm chart and Argo CD application. Bootstrap may install Argo CD, but Argo CD reconciles the workload.

## Consequences

Deployment changes are declarative and reviewable. Local bootstrap needs a repository source reachable by Argo CD, with an explicit local development workflow.

