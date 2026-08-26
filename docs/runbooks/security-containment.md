# Security containment runbook

1. Confirm the event came from an allowlisted Tetragon policy and links to a central incident.
2. Review normalized process/network fields, evidence reference, risk factors, and OPA result.
   Raw argv, environment variables, credentials, and request headers are never evidence.
3. Confirm the live target is one controller-managed pod in `cloudward-staging` with
   `cloudward.io/demo-target=true`.
4. Apply containment through the CloudWard action endpoint. Do not create an ad hoc policy.
5. Require policy selector, target label, blocked internal egress, and preserved readiness to pass.
6. Investigate using the incident timeline. Part 2 never performs destructive follow-up.
7. Remove containment through CloudWard and require policy absence, label removal, and restored
   internal connectivity. A failed verification escalates; it is never marked resolved.

