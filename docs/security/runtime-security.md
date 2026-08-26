# Runtime security architecture

CloudWard uses pinned Tetragon 1.7.0 as a read-only runtime sensor. Three namespaced
`TracingPolicyNamespaced` resources observe only pods in `cloudward-staging` carrying
`cloudward.io/demo-target=true`. Tetragon does not decide or execute remediation.

The node-local forwarder reads Tetragon's bounded JSON export from a read-only host mount. It
filters to the three CloudWard policy names, converts events to an allowlisted schema, removes
raw arguments and environment data, redacts secret patterns, deduplicates, rate-limits, and
delivers a signed request to `/api/v1/webhooks/security/tetragon`. It has no Kubernetes API token
or write RBAC. Production deployments must use HTTPS; the HTTP host-bridge exception exists only
for local k3d.

The public webhook verifies HMAC, timestamp, one-time nonce, body size, rate limit, schema,
policy/category pair, staging namespace, and demo label, then returns 202 only after publishing an
idempotent Celery job. The worker calls a bearer-authenticated internal API; that endpoint
recomputes the fingerprint before processing. PostgreSQL stores one aggregate per fingerprint
window, not an unbounded raw process stream. A new accepted job creates an incident in the central
state machine, a `SECURITY_EVENT` evidence snapshot, a deterministic central risk result, an
action proposal, an OPA decision, audit events, and an SSE record. Worker retries are safe because
the database fingerprint gate converts repeated delivery into a deduplication update.

## Cilium quarantine

`APPLY_QUARANTINE` is a typed operation. The executor re-reads the live pod and refuses any
namespace except `cloudward-staging`, any pod without the demo label, or an unmanaged pod. It adds
a unique label to exactly one pod and creates one `CiliumNetworkPolicy` with an explicit
`egressDeny` to all destinations. No shell, arbitrary kubectl, arbitrary selector, or arbitrary
policy body is accepted.

Containment is considered verified only when all four checks pass: the exact Cilium policy is
present, its selector matches the exact quarantine label, the fixed internal simulator was
reachable before but is blocked after, and pod readiness remains healthy. Removal deletes only
the recorded policy, removes only the recorded label, proves the policy and label are absent,
and proves internal connectivity is restored. Every lifecycle change is persisted and audited.

## Operations

Set the same 32+ character `TETRAGON_WEBHOOK_SECRET` for Docker Compose and the install script,
then run `make tetragon-install`. Override `CLOUDWARD_SECURITY_API_URL` when CloudWard is exposed
on a port other than 8080. `make tetragon-validate` checks component health; each S1-S3 script
then proves the real event and containment path.

Cleanup is always performed through
`POST /api/v1/security/events/{id}/containment/remove`; deleting policies manually would leave an
incorrect lifecycle record and is not an accepted cleanup procedure.
