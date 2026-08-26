# ADR-028: Production promotion through pull request

- Status: Accepted
- Date: 2026-08-22

## Context

Deployment readiness is necessary but insufficient evidence for production, and
an automated release should not approve its own risk.

## Decision

The release workflow updates staging only. A separate validation records health,
smoke, security-admission, scan, and SBOM evidence. A manual promotion workflow
then opens a production GitOps PR containing the exact digest, source, evidence,
risk notes, and rollback digest. A human-approved merge is the production
authority; Argo CD subsequently reconciles Git.

## Consequences

Production is never promoted automatically in v1 and direct Kubernetes mutation
cannot bypass the review record. Promotion has more latency and requires branch
protection, reviewers, and a healthy GitHub App integration.
