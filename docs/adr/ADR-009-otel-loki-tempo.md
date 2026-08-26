# ADR-009: OpenTelemetry, Loki, and Tempo observability model

- Status: Accepted
- Date: 2026-08-22

## Context

Incident evidence needs metrics, structured logs, and traces that an operator can correlate without introducing overlapping agents or high-cardinality metric/log labels.

## Decision

Use one OpenTelemetry Collector DaemonSet for OTLP ingestion and Kubernetes container logs. Export traces to Tempo and logs through Loki's native OTLP endpoint. Prometheus scrapes application metrics directly. Keep trace and span IDs as searchable structured log fields, not Prometheus labels or Loki stream labels. Provision Grafana navigation between all three data sources.

## Consequences

The local pipeline has one collection layer and explicit destinations. Kubernetes metadata and trace correlation are consistent. The collector is node-aware and therefore has read-only Kubernetes metadata/log permissions; telemetry stores remain responsible for query and retention behavior.
