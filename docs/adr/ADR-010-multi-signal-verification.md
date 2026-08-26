# ADR-010: Multi-signal remediation verification

- Status: Accepted
- Date: 2026-08-22

## Context

A successful Kubernetes API call does not prove that a service recovered, and a single green health endpoint can hide elevated errors, latency, restarts, or failed containment.

## Decision

Require runbook-defined verification to compare bounded before/after evidence across relevant Kubernetes state, Prometheus metrics, Loki logs, Tempo traces, readiness, and synthetic requests. An incident reaches `RESOLVED` only when every required typed condition passes. Reversible, policy-permitted rollback remains an allowlisted action; retries remain capped at three.

## Consequences

Resolution is evidence-backed and false recovery is less likely. Verification takes longer and can fail when a telemetry dependency is unavailable; CloudWard must then fail closed or escalate rather than manufacture success.
