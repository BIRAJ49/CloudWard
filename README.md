# CloudWard

**CloudWard — Autonomous Cloud Reliability, Security & FinOps Platform**

CloudWard is a production-style platform-engineering project for safe, auditable local operations. Parts 1 and 2 established the deterministic control plane, real telemetry, bounded reliability remediation, runtime-security detection, verified containment, and the local Incident Lab. Part 3 adds controlled AI diagnosis, Git/source correlation, structured incident memory, deterministic OpenCost-backed FinOps, transactional approvals, GitHub App automation, Teams notifications, supply-chain enforcement, and staging-to-production GitOps promotion.

CloudWard is deliberately not an LLM wired to `kubectl`. AI may diagnose, summarize, correlate, and select candidates from the action allowlist; it cannot authorize or execute. Every action remains typed, risk-scored, OPA-controlled, approval-gated when required, bounded, reversible where required, and audited. Part 3 remains local and provisions no AWS infrastructure.

## Part 3 architecture

```text
Browser -> Nginx -> React dashboard
                 -> FastAPI modular monolith -> PostgreSQL
                                             -> Redis -> Celery worker
                                             -> OPA
                                             -> Kubernetes API
                                             -> OpenRouter provider boundary
                                             -> GitHub App / Teams adapters

Signed digest release -> staging GitOps -> Argo CD -> Helm demo release
Validated staging state -> human-reviewed promotion PR -> production GitOps

Demo + Kubernetes -> Prometheus / Loki / Tempo <- OpenTelemetry Collector
Prometheus -> Alertmanager -> authenticated CloudWard webhook -> Celery workflow
Tetragon -> bounded forwarder -> authenticated security webhook -> Celery workflow
OpenCost + Prometheus -> deterministic FinOps engine -> recommendation / GitHub PR
Incident Lab -> OPA -> nine bounded reliability, security, or FinOps scenarios
```

The executable workflow is fixed:

```text
EVENT -> EVIDENCE -> RUNBOOK + INCIDENT MEMORY -> OPTIONAL AI DIAGNOSIS
      -> ALLOWLISTED CANDIDATES -> RISK -> OPA
      -> APPROVAL WHEN REQUIRED -> ALLOWLISTED ACTION -> VERIFICATION
      -> RESOLUTION / BOUNDED RETRY + ESCALATION -> AUDIT
```

The first runbook handles one unhealthy, controller-managed demo pod in `cloudward-staging`. CloudWard may delete that pod only after every gate allows it. The Kubernetes Deployment controller creates the replacement replica; CloudWard then verifies ready replicas, pod readiness, and application health before resolving the incident.

See the [AI architecture](docs/ai/openrouter.md), [dashboard design](docs/dashboard/operations-dashboard.md), [supply-chain pipeline](docs/supply-chain/pipeline.md), [GitOps promotion model](docs/gitops/promotion.md), and [remediation safety boundary](docs/architecture/safety-boundary.md).

## Repository map

```text
backend/             FastAPI domains, SQLAlchemy models, Alembic, and tests
worker/              Celery app, queues, workflows, and test task
frontend/            React operations dashboard and tests
demo-services/api/   Controlled FastAPI demo workload
demo-services/c2-simulator/ Internal-only S2 destination
security-forwarder/  Bounded Tetragon event forwarder
policies/opa/        Rego policy and policy tests
runbooks/            Typed declarative remediation runbooks
k8s/                 Namespaces, RBAC, and cluster bootstrap manifests
helm/                 Demo service chart and environment values
cloudward-gitops/    Argo CD desired state for the local demo
scripts/             Reproducible local cluster and scenario commands
docker/              Container and Nginx configuration
docs/                Architecture, ADRs, operations, runbooks, and tests
```

The control plane remains a modular monolith. Telemetry stores and Kubernetes sensors are separate local platform components; decision authority remains in CloudWard and OPA.

## Prerequisites

For the control plane:

- Docker Engine or Docker Desktop with Compose v2
- `make`

For native development and the complete cluster demo:

- Python and Node.js versions supported by the project manifests
- `uv` for locked Python development and test environments
- `kubectl`, Helm, and k3d (Cilium itself is installed by the bootstrap script)
- enough local Docker capacity for the control plane and Kubernetes components

No AWS account or cloud credentials are used.

## Start the control plane

Create the ignored local environment file and replace all placeholders:

```bash
make setup
```

Generate a session secret, choose local-only PostgreSQL credentials, and keep them in `.env`. Never commit that file. Then validate and start the stack:

```bash
make compose-config
make up
make migrate
```

Nginx is the single intended host entry point. Useful endpoints include:

- `GET /health/live` — process liveness
- `GET /health/ready` — PostgreSQL, Redis, and OPA readiness
- `GET /api/v1/incidents` — incident collection
- `GET /api/v1/incidents/{id}` — incident details
- `GET /api/v1/incidents/{id}/events` — append-oriented timeline
- `GET /api/v1/incidents/{id}/audit` — decision/action audit history
- `GET /api/v1/incidents/{id}/diagnosis` — operator-facing advisory diagnosis
- `GET /api/v1/incidents/{id}/similar` — deterministic structured-memory matches
- `GET /api/v1/approvals` — transactional approval queue
- `GET /api/v1/finops/recommendations` — bounded FinOps recommendations
- `GET /api/v1/audit` — bounded global audit feed
- `GET /api/v1/gitops/drift/{environment}` — desired-versus-live GitOps state
- `GET /api/v1/integrations/github` — non-secret GitHub App readiness
- `GET /api/v1/integrations/teams` — non-secret Teams readiness
- `POST /api/v1/webhooks/alertmanager` — authenticated Alertmanager intake
- `POST /api/v1/webhooks/security/tetragon` — authenticated runtime-event intake
- `GET /api/v1/security/events` — normalized runtime detections
- `GET /api/v1/scenarios` — closed Incident Lab catalog
- `GET /api/v1/events/stream` — authorized server-sent event stream
- `GET /docs` — generated OpenAPI UI in development

Exact request schemas are available through OpenAPI. Normal clients receive structured error envelopes with the request ID; stack traces and credentials are not exposed.

## Authentication and roles

GitHub OAuth is the production authentication design. Local testing can use the separate development provider only when the environment is explicitly `development`; startup rejects a development bypass in production.

Backend authorization—not hidden buttons—enforces these roles:

| Role | Capabilities |
| --- | --- |
| Viewer | Read platform, cluster/service, incident, and audit state |
| Operator | Viewer access plus standard operational approvals/rejections and controlled demo actions |
| Admin | Operator access plus role mappings, settings/policy administration, and permitted higher-risk approvals |

## Create the local Kubernetes platform

```bash
make cluster-create
make cluster-bootstrap
make finops-install
make supply-chain-install
make cluster-validate
```

Creation disables the default k3s CNI so Cilium is the intended networking layer. Bootstrap installs the Part 1/2 platform; the explicit Part 3 targets add pinned OpenCost plus Kyverno signature enforcement and GitOps drift visibility. The platform establishes the staging safety boundary and lets Argo CD reconcile Helm-packaged, digest-pinned demo workloads.

The demo deployment has at least two replicas and carries:

```yaml
cloudward.io/demo-target: "true"
```

The production namespace exists to exercise policy differences; the automated destructive demo does not target it.

## Run Part 3 locally

Keep the telemetry bridge running so the Compose API can query Prometheus, Loki, Tempo, and OpenCost inside the cluster:

```bash
make telemetry-bridge
```

Open Grafana separately at `http://127.0.0.1:3001`:

```bash
make observability
```

Use the Incident Lab page for the closed R1–R4, S1–S3, and F1–F2 catalog, or run one of the fixed security helpers under `scripts/scenarios/security/`. The original deterministic Part 1 incident remains available:

```bash
make trigger-demo
```

Follow every execution in the React dashboard, API, Grafana, or structured logs. A completed workflow records:

1. incident creation and evidence collection;
2. deterministic reliability, security, or FinOps classification and runbook selection;
3. structured incident-memory lookup and optional advisory AI diagnosis;
4. the six-factor risk calculation;
5. OPA's decision and reason;
6. transactional approval when policy requires it;
7. the typed remediation, containment, or GitOps proposal;
8. bounded before/after evidence and multi-signal verification;
9. notifications and the complete incident-event and audit histories.

Verification failure retries according to policy, with no more than three automatic attempts, then escalates. Unknown actions, invalid transitions, unvalidated runbooks, and OPA failures fail closed.

## Test and validate

```bash
make backend-lint
make backend-test
make worker-test
make demo-test
make frontend-lint
make frontend-test
make compose-config
make cluster-validate
```

Service integration tests require the Compose dependencies. Kubernetes, signature-admission, and end-to-end tests require the bootstrapped k3d cluster and real immutable image fixtures. An unavailable dependency is blocked, not passed.

## Stop and clean up

```bash
make down
make cluster-destroy
```

The destroy script targets only the explicitly named CloudWard k3d cluster. It does not touch AWS or unrelated local clusters.

## Deliberately deferred after Part 3

AWS Terraform deployment, remote Terraform state, VPC/EKS networking, EKS validation, EC2 control-plane hosting, Karpenter, AWS load balancing, public Cloudflare deployment, AWS budgets, and production cloud teardown remain deferred to Part 4. No AWS resource is provisioned by Part 3.

## License

Apache License 2.0. See [LICENSE](LICENSE).
