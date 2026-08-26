# Local development operations

## Prerequisites

- Docker with Compose v2
- Python supported by `backend/pyproject.toml`
- `uv` for locked Python environments
- Node.js supported by `frontend/package.json`
- `kubectl`, `helm`, and `k3d` for the full cluster demonstration; bootstrap installs Cilium

Copy `.env.example` to `.env` and replace every `replace-me` value with local-only values. Do not commit `.env`.

## Control plane

```bash
make setup
make compose-config
make up
make migrate
```

Use `docker compose ps` and `docker compose logs --follow` to inspect service state. Nginx is the intended browser entry point. The API process exposes liveness and dependency-aware readiness behind it.

Stop the control plane with:

```bash
make down
```

## Local Kubernetes

The cluster scripts use the fixed cluster name `cloudward` and context `k3d-cloudward`. They must reject unsafe or ambiguous targets.

```bash
make cluster-create
make cluster-bootstrap
make cluster-validate
```

Bootstrap installs and verifies Cilium before continuing, installs Argo CD and Kyverno, creates staging and production namespaces through desired-state manifests, and registers the demo Helm application with Argo CD.

After the environment is healthy, run the controlled scenario with:

```bash
make trigger-demo
```

Observe the incident through the dashboard or `/api/v1/incidents`. The expected execution deletes one unhealthy pod; the Deployment controller reconciles the missing replica. CloudWard resolves the incident only after readiness and application-health checks pass.

Cleanup removes only the explicitly named local cluster:

```bash
make cluster-destroy
```

## Development authentication

GitHub OAuth is the production authentication path. A test identity provider may be enabled only when both `APP_ENV=development` and `DEV_AUTH_ENABLED=true`. Startup rejects the bypass in staging and production.
