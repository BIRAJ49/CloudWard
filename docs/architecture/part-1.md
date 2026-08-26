# CloudWard Part 1 architecture

CloudWard Part 1 is a local, deterministic reliability control plane. The FastAPI application is a modular monolith: each domain owns its models and services, while one process exposes a versioned API. Celery workers execute asynchronous work using Redis, PostgreSQL is the system of record, and OPA is the final policy authority for remediation.

## Decision and execution path

```text
controlled event
  -> incident + correlation ID
  -> Kubernetes and health evidence
  -> deterministic classification
  -> version-controlled runbook match
  -> deterministic risk calculation
  -> OPA policy decision
  -> approval gate, when required
  -> allowlisted typed Kubernetes action
  -> deployment, pod, and application verification
  -> resolution or bounded retry and escalation
  -> append-oriented incident and audit history
```

An AI subsystem is intentionally absent from Part 1. Future diagnosis can propose facts or actions, but it cannot bypass runbook validation, risk calculation, OPA, approval, the action registry, verification, or audit.

## Components

| Component | Responsibility | Trust boundary |
| --- | --- | --- |
| Nginx | Single local HTTP entry point, API/UI routing, security headers | Does not make remediation decisions |
| React UI | Operational overview, incident list, incident evidence and decision timeline | Read-only for viewers; backend enforces every permission |
| FastAPI | Domain orchestration, REST API, auth/RBAC, incident lifecycle | Cannot execute an action absent registry and policy approval |
| PostgreSQL | Durable platform, incident, decision, execution, and audit records | Schema managed exclusively through Alembic |
| Redis | Celery broker/result transport and readiness dependency | Contains no authoritative incident history |
| Celery | Queue-isolated worker foundation and real broker round-trip task | Remediation orchestration remains in the modular API for Part 1 |
| OPA | Final action policy decision and absolute deny rules | Numeric risk never overrides a hard deny |
| Kubernetes API | Typed evidence and allowlisted pod deletion | Access is namespace- and RBAC-scoped |
| Argo CD | Reconciles desired demo workload from GitOps definitions | Normal workload deployment does not use ad hoc apply |
| Cilium | Local cluster networking | Installed before workloads and verified healthy |
| Kyverno | Admission-policy baseline | Prevents privileged/host-level demo workloads and unsafe capabilities |

## Module boundaries

Backend modules communicate through explicit service functions and typed schemas. HTTP handlers authorize and validate input, domain services own state transitions and persistence, policy and Kubernetes adapters isolate external APIs, and audit recording remains append-oriented. Arbitrary shell commands, arbitrary `kubectl` strings, and caller-supplied external URLs are not execution primitives.

The first supported action is `DELETE_UNHEALTHY_POD`. CloudWard deletes only the selected unhealthy, controller-managed pod after evidence, risk, and OPA gates pass. The Kubernetes Deployment controller—not CloudWard—creates the replacement replica.

## Persistence and traceability

UTC timestamps, UUID identifiers, request IDs, and correlation IDs connect API requests, incident events, evidence, risk, policy decisions, executions, verification, and audit records. Incident-event and audit rows are historical records; normal flows append rather than rewrite history.

## Failure behavior

Dependency readiness is reported independently for PostgreSQL, Redis, and OPA. Invalid incident transitions are controlled domain errors. Failed verification cannot resolve an incident: the workflow retries only within the configured maximum of three automatic attempts, then transitions to `ESCALATED`. Policy denial transitions to `BLOCKED` or `ESCALATED` according to the decision and records why.
