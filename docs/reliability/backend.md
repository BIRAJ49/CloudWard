# Part 2 reliability backend

Alertmanager posts version-4 payloads to `POST /api/v1/webhooks/alertmanager` using a bearer token stored outside Git. CloudWard bounds the body, validates a strict schema, redacts annotations, derives a stable fingerprint, and reuses the active incident. Exact duplicates increment a counter instead of creating another incident or action.

The webhook enqueues `cloudward.tasks.alerts.process`. The worker collects bounded Kubernetes, Prometheus, Loki, and Tempo evidence, selects a versioned deterministic runbook, calculates risk, records OPA's decision, claims a typed action with an idempotency key, and advances to multi-signal verification. Operational actions remain limited to three attempts.

Verification stores before/after readiness, pod count, restarts, error rate, p95 latency, health, and a synthetic request. It must pass before `RESOLVED`. R4 records `PLATFORM_SELF_HEALING`. Reversible low-risk scale actions record and restore their prior replica count; stale targets and values above `MAX_TEMPORARY_REPLICAS` are rejected.

Incident Lab exposes `GET /api/v1/scenarios`, `POST /api/v1/scenarios/{id}/start`, `GET /api/v1/executions/{id}`, `POST /api/v1/executions/{id}/stop`, and `GET /api/v1/events/stream`. Only the seven server-owned Part 2 scenarios are exposed. The backend, OPA, and Kyverno enforce `cloudward-staging` plus `cloudward.io/demo-target=true`.

R1 uses a writable ephemeral Git source exposed only through the k3d loopback port. Incident Lab commits the fixed `local-bad` tag to the fixed local values path; remediation commits `local` back to the same branch. Argo CD performs both rollouts. Repository URL, branch, file path, and both tags are constants, git calls use fixed argv without a shell, file replacement is atomic, and stale tag transitions fail closed. Persistent rollback can never auto-execute and requires explicit approval. CloudWard never patches the Deployment or leaves Git inconsistent. Existing clusters must be recreated once to obtain the loopback Git port and writable ephemeral repository.

R2 uses bounded `StressChaos` and scale-up. R3 uses bounded memory stress and OOM evidence without unbounded memory growth. R4 uses `PodChaos`, observes Kubernetes reconciliation, and takes no credit for it.
