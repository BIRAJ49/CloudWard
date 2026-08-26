# Incident operations

An operator should use the incident timeline as the authoritative explanation of what CloudWard observed and decided. Each state transition, evidence snapshot, selected runbook, risk breakdown, OPA result, execution, verification, and terminal result carries a shared correlation ID.

For an incident waiting for approval, inspect the target environment, action metadata, evidence freshness, risk factors, runbook preconditions, and OPA reason before approving or rejecting it. Frontend controls are conveniences only; backend RBAC enforces the permission.

For `BLOCKED` incidents, correct the policy, unsupported action, unsafe target, or missing evidence rather than bypassing a gate. For `ESCALATED` incidents, stop automated retries, inspect the three recorded attempts and verification checks, and intervene through an external, authorized operational process. Never mutate historical incident-event or audit records to hide a failure.

