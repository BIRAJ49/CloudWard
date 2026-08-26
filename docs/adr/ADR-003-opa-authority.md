# ADR-003: OPA as final remediation policy authority

- Status: Accepted
- Date: 2026-08-13

## Context

Risk scores summarize operational risk but can be wrong or manipulated and must not grant permission.

## Decision

Send a structured action context to a separately running OPA service. OPA returns allow, approval, and reason fields and enforces absolute hard denials independent of numeric risk.

## Consequences

Policy is testable and reviewable outside application code. OPA unavailability fails closed for action execution.

