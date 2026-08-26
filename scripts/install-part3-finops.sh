#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command helm
require_command kubectl
require_context

project_root="$(repo_root)"
readonly project_root

log "Creating the isolated OpenCost namespace"
kubectl apply -f "$project_root/k8s/namespaces/opencost.yaml"

log "Adding the official OpenCost Helm repository"
helm repo add opencost https://opencost.github.io/opencost-helm-chart --force-update
helm repo update

log "Installing OpenCost chart ${OPENCOST_CHART_VERSION} against the existing Prometheus"
helm upgrade --install opencost opencost/opencost \
  --namespace opencost \
  --version "$OPENCOST_CHART_VERSION" \
  --values "$project_root/k8s/opencost/values.yaml" \
  --rollback-on-failure --wait --timeout 10m

log "OpenCost installed locally. Keep scripts/port-forward-telemetry.sh running for the Compose API."
