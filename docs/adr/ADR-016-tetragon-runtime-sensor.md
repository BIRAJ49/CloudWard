# ADR-016: Tetragon is a runtime sensor

Status: Accepted

Tetragon provides kernel/eBPF runtime telemetry through tightly scoped namespaced tracing
policies. CloudWard normalizes and classifies that telemetry; Tetragon does not become the general
decision engine. This preserves one incident, risk, OPA, action, verification, and audit model.

