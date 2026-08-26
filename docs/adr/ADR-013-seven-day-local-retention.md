# ADR-013: Seven-day logical local telemetry retention

- Status: Accepted
- Date: 2026-08-22

## Context

The portfolio needs enough telemetry to investigate recent scenarios without allocating production-scale storage on a developer machine. The k3d profile intentionally has no dynamic storage provisioner.

## Decision

Configure Prometheus, Loki, and Tempo for a logical 168-hour retention window. Bound Prometheus and Loki local volumes at 8 GiB, use ephemeral local storage, and set explicit CPU/memory requests and limits for all components.

## Consequences

Approximately one week of recent telemetry is queryable when capacity and pod lifetime permit. Data can disappear on pod or cluster recreation, so the setting is not a durability guarantee. Production requires durable storage, backups, and independent capacity planning.
