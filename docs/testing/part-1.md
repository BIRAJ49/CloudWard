# Part 1 testing strategy

Tests follow the boundary where failures are cheapest to diagnose.

## Local suites

```bash
make backend-lint
make backend-test
make worker-test
make demo-test
make frontend-lint
make frontend-test
make platform-test
make compose-config
```

Backend unit tests cover risk boundaries, every incident transition, runbook rejection, action-registry allowlisting, RBAC, policy result handling, verification, and retry limits. API tests cover health, incident resources, structured errors, and authorization. Frontend tests cover the overview and incident states visible to an operator.

## Service integration

Start Compose and apply migrations before running tests marked `integration`. The suite must use real PostgreSQL, Redis, Celery, and OPA endpoints. A green unit suite is not evidence that these integrations pass.

At minimum, prove that a Celery test task is published through Redis and completed by the worker, that migrations upgrade an empty PostgreSQL database and safely downgrade/re-upgrade, and that OPA denies a hard-denied action submitted with risk score `1`.

## Kubernetes and end-to-end

The cluster validation checks k3d connectivity, Cilium, Argo CD, Kyverno, both namespaces, the Argo-managed Helm release, two ready demo replicas, and the required demo-target label. The end-to-end test triggers one deterministic unhealthy target and records the selected pod UID so it can prove that:

- policy allowed exactly the registered action;
- the original unhealthy pod was deleted;
- the Deployment controller produced a different pod UID;
- ready replica count returned to the desired value;
- the application health signal passed;
- the incident reached `RESOLVED` only after verification;
- the event timeline and audit trail contain the complete lifecycle.

If Docker or cluster tooling is unavailable, report these checks as blocked, never as passed.
