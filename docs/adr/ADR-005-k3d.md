# ADR-005: k3d for local Kubernetes

- Status: Accepted
- Date: 2026-08-13

## Context

The portfolio needs a reproducible multi-component Kubernetes demonstration without provisioning cloud infrastructure.

## Decision

Use a named k3d cluster with automated create, bootstrap, validate, and destroy scripts.

## Consequences

The environment is disposable and CI-friendly while using the Kubernetes API semantics needed by the remediation workflow. Host capacity remains a practical constraint.

