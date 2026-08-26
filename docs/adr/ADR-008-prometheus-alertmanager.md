# ADR-008: Prometheus and Alertmanager for deterministic alerting

- Status: Accepted
- Date: 2026-08-22

## Context

CloudWard needs repeatable signals for controlled reliability failures. A single request failure must not become a remediation instruction, and continuing alerts must remain groupable and deduplicatable.

## Decision

Use Prometheus Operator resources for bounded metric scraping and sustained alert rules. Route firing and resolved alerts through Alertmanager to an authenticated CloudWard webhook. Alerts contain evidence and stable classification labels; CloudWard independently validates, normalizes, deduplicates, selects a runbook, calculates risk, and asks OPA.

## Consequences

The detection path is observable and deterministic. Demo windows can remain short while production thresholds are explicitly separate. Prometheus and Alertmanager do not receive authority to execute remediation.
