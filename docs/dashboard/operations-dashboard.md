# CloudWard operations dashboard

The React application is a factual operations console for the local CloudWard control plane. It uses the same-origin `/api/v1` API with the authenticated session cookie; no integration secret is compiled into the browser bundle.

## Views

- Overview combines dependency health, cluster inventory, active incidents, security containment, approvals, calculated FinOps savings, deployments, pull requests, and recent audit records. A failed data source is shown as unavailable rather than zero.
- Incidents provides status, severity, service, environment, category, resolution-source, and date filters over the records returned by the API.
- Incident detail separates model-generated diagnosis from the deterministic runbook, risk score, OPA decision, approval, typed action execution, and multi-signal verification record. Hidden model reasoning is neither requested nor displayed.
- Security shows normalized runtime events and verified Cilium containment state.
- FinOps shows only deterministic recommendations backed by a bounded evidence window. Missing data produces no invented cost or savings.
- Approvals is read-only for Viewers. Operator and Admin decisions include a durable comment and remain subject to expiry, stale-target checks, policy, and at-most-once execution.
- Clusters and Services expose returned inventory without synthetic health.
- Audit Log exposes a bounded, newest-first view of append-oriented events.
- Incident Lab lists the closed catalog of four reliability, three security, and two FinOps scenarios. The backend remains the safety authority for staging namespace, target labels, timeouts, and cleanup.
- Settings exposes only safe session and integration readiness metadata.

## Live updates

The dashboard consumes the authenticated `/api/v1/events/stream` endpoint. Durable event IDs are retained across client reconnects through `last_event_id`. The stream covers incident lifecycle, remediation, verification, approvals, security, FinOps, and Incident Lab execution events. Manual refresh remains available and no polling loop is used.

## Authorization boundary

Frontend role checks exist only to present the correct controls. Every write endpoint independently enforces backend RBAC, transactional idempotency, stale-action protection, risk policy, and OPA. AI output is informational and cannot invoke an executor.
