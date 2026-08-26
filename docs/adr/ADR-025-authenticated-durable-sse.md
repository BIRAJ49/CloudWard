# ADR-025: Authenticated durable SSE for operations updates

Status: Accepted

CloudWard uses a same-origin, session-authenticated Server-Sent Events stream for one-way
operations updates. Events are first persisted in PostgreSQL and carry monotonically increasing
IDs. Clients reconnect with the last observed ID so brief network failures do not silently lose
incident, remediation, verification, approval, security, FinOps, or Incident Lab transitions.

SSE fits the dashboard's server-to-browser update pattern without introducing a second
bidirectional protocol or a polling loop. Backend RBAC remains authoritative, payloads pass
through the standard redactor, replay is bounded, and the reverse proxy disables buffering.
