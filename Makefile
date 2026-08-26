SHELL := /bin/sh

.PHONY: help setup compose-config up down logs migrate backend-test backend-lint worker-test demo-test frontend-test frontend-lint platform-test test cluster-create cluster-bootstrap cluster-validate cluster-validate-part2 tetragon-install tetragon-validate cluster-destroy observability telemetry-bridge trigger-demo finops-install finops-render supply-chain-install staging-validate promotion-assets-test signature-admission-test

help:
	@awk 'BEGIN {FS = ":.*## "; print "CloudWard Part 3 — intelligent local operations platform\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create local environment files from safe examples
	@test -f .env || cp .env.example .env

compose-config: ## Validate the Docker Compose model
	docker compose config --quiet

up: ## Start the local CloudWard control plane
	docker compose up --build -d

down: ## Stop the local CloudWard control plane
	docker compose down

logs: ## Follow control-plane logs
	docker compose logs --follow

migrate: ## Apply database migrations in the API container
	docker compose run --rm api alembic upgrade head

backend-test: ## Run backend tests
	cd backend && uv run --frozen pytest

backend-lint: ## Run backend formatting and static checks
	cd backend && uv run --frozen ruff format --check . && uv run --frozen ruff check . && uv run --frozen mypy app

worker-test: ## Run worker lint and unit tests
	cd worker && uv run --frozen ruff format --check . && uv run --frozen ruff check . && uv run --frozen pytest -m 'not integration'

demo-test: ## Run demo-service lint and tests
	cd demo-services/api && uv run --frozen ruff format --check . && uv run --frozen ruff check . && uv run --frozen pytest

frontend-test: ## Run frontend tests once
	npm --prefix frontend test -- --run

frontend-lint: ## Run frontend lint and production build
	npm --prefix frontend run lint && npm --prefix frontend run build

platform-test: ## Validate shell, OPA, Helm, and Kubernetes manifests
	./scripts/test-platform-assets.sh

test: backend-test worker-test demo-test frontend-test platform-test ## Run local unit/API and static platform suites

cluster-create: ## Create the k3d cluster with Cilium-compatible settings
	./scripts/cluster-create.sh

cluster-bootstrap: ## Install Cilium, Argo CD, Kyverno, and GitOps applications
	./scripts/cluster-bootstrap.sh

cluster-validate: ## Validate the local platform and demo workload
	./scripts/validate-platform.sh

cluster-validate-part2: ## Validate Part 2 telemetry ingestion and correlation
	./scripts/validate-part2-platform.sh

tetragon-install: ## Install pinned Tetragon, forwarder, and controlled security simulator
	./scripts/install-tetragon.sh

tetragon-validate: ## Validate the local runtime-security components
	./scripts/validate-tetragon.sh

cluster-destroy: ## Delete only the named CloudWard k3d cluster
	./scripts/cluster-destroy.sh

observability: ## Open a local Grafana port-forward on http://127.0.0.1:3001
	./scripts/port-forward-observability.sh grafana

telemetry-bridge: ## Bridge Prometheus, Loki, and Tempo to the Compose API
	./scripts/port-forward-telemetry.sh

trigger-demo: ## Trigger the controlled unhealthy-pod incident
	./scripts/e2e-unhealthy-pod.sh

finops-install: ## Install pinned local OpenCost against the existing Prometheus
	./scripts/install-part3-finops.sh

finops-render: ## Render pinned OpenCost manifests without installing them
	./scripts/render-part3-finops.sh

supply-chain-install: ## Install local Kyverno signature policy and GitOps drift visibility
	./scripts/install-part3-supply-chain.sh

staging-validate: ## Validate a real digest-pinned staging release (IMAGE_REPOSITORY and IMAGE_DIGEST required)
	@test -n "$(IMAGE_REPOSITORY)" && test -n "$(IMAGE_DIGEST)"
	./scripts/gitops/validate-staging.sh "$(IMAGE_REPOSITORY)" "$(IMAGE_DIGEST)"

promotion-assets-test: ## Exercise immutable staging-to-production promotion mechanics locally
	./scripts/gitops/test-promotion-assets.sh

signature-admission-test: ## Exercise real unsigned, wrong-signer, and approved-signer admission cases
	./scripts/supply-chain/test-signature-admission.sh
