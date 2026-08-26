# ADR-002: Deterministic runbooks before AI

- Status: Accepted
- Date: 2026-08-13

## Context

An unconstrained model-to-cluster path is neither auditable nor a safe remediation authority.

## Decision

Part 1 uses typed, version-controlled YAML runbooks and deterministic incident matching. AI integration is deferred and will remain advisory behind the same safety gates.

## Consequences

Every executable action has reviewable preconditions and verification. Novel incidents may escalate rather than improvise an unsafe command.

