# Microsoft Teams notifications

Set `TEAMS_WORKFLOW_WEBHOOK_URL` only in the local secret environment or deployment secret store. It is consumed exclusively by the backend and is never returned by the API, included in SSE, written to notification payloads, or placed in React configuration. `GET /api/v1/integrations/teams` reports only readiness, enabled event names, retry limits, and aggregate delivery counts.

Business workflows enqueue channel-neutral notification records. `DashboardNotifier`, `TeamsNotifier`, and `GitHubIssueNotifier` implement the delivery boundary. A Celery task calls an authenticated internal API, applies bounded exponential retry, and persists attempts, delivery time, the redacted error code, and audit events. Delivery failure cannot reverse or fail a successful remediation transaction.

Teams delivery accepts only HTTPS Microsoft Workflows host families and sends a concise adaptive card containing severity, service, environment, incident, cause, risk, policy, current state, and an optional dashboard link. Configure `NOTIFICATION_EVENTS` to avoid messages for minor state transitions. The supported defaults are critical detection, approval required, security containment, remediation failure, escalation, and resolution.

GitHub Issue delivery is used for configured escalation/failure notifications and delegates to the GitHub App issue service. That service applies repository allowlisting and incident-level deduplication.
