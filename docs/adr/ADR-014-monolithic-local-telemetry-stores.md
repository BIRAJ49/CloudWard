# ADR-014: Monolithic Loki and Tempo for local k3d

- Status: Accepted
- Date: 2026-08-22

## Context

Distributed Loki/Tempo topologies require object storage and several processes whose operational cost obscures the reliability workflow on a small local cluster.

## Decision

Run one monolithic Loki replica behind its gateway and one Tempo replica with local storage. Disable Loki's distributed read/write/backend replicas and caches. Keep Grafana and Prometheus single-replica as well.

## Consequences

The architecture is understandable and resource-bounded for demonstrations. It has no high availability and must not be copied into production. A future production design must select durable object storage and failure-domain-aware deployments deliberately.
