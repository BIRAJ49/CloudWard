# ADR-001: Modular monolith for the control plane

- Status: Accepted
- Date: 2026-08-13

## Context

The Part 1 domains need strong ownership boundaries, but independent network services would add deployment and failure complexity before scaling evidence exists.

## Decision

Implement one FastAPI control-plane deployment with domain modules, explicit service interfaces, one PostgreSQL schema, and Celery workers for asynchronous boundaries.

## Consequences

Local development, transactions, migrations, and tracing stay understandable. A future domain can be extracted behind an existing interface if workload or isolation requirements justify it.

