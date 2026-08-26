# ADR-004: Hybrid direct-action and GitOps remediation

- Status: Accepted
- Date: 2026-08-13

## Context

Ephemeral recovery and persistent desired-state changes have different consistency requirements.

## Decision

Permit narrowly scoped, reversible, policy-approved direct actions for ephemeral resources, such as deleting one unhealthy controller-managed pod. Represent persistent configuration changes as reviewed GitOps changes.

## Consequences

The fast recovery path remains small. Durable changes preserve review, reconciliation, and provenance rather than creating configuration drift.

