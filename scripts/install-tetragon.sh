#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command docker
require_command helm
require_command k3d
require_command kubectl
require_context

project_root="$(repo_root)"
readonly project_root

env_value() {
  local key="$1"
  local env_file="$project_root/.env"
  [[ -f "$env_file" ]] || return 0
  awk -v key="$key" 'index($0, key "=") == 1 {sub("^[^=]*=", ""); print; exit}' "$env_file"
}

webhook_secret="${TETRAGON_WEBHOOK_SECRET:-}"
if [[ -z "$webhook_secret" ]]; then
  webhook_secret="$(env_value TETRAGON_WEBHOOK_SECRET)"
fi
readonly webhook_secret
readonly security_api_url="${CLOUDWARD_SECURITY_API_URL:-http://host.k3d.internal:8080/api/v1/webhooks/security/tetragon}"

[[ "${#webhook_secret}" -ge 32 ]] || die "TETRAGON_WEBHOOK_SECRET must contain at least 32 characters"
[[ "$webhook_secret" != replace-me* ]] || die "TETRAGON_WEBHOOK_SECRET is still a placeholder"
[[ "$security_api_url" == */api/v1/webhooks/security/tetragon ]] ||
  die "CLOUDWARD_SECURITY_API_URL must use the Tetragon webhook path"

log "Building and importing the bounded security demo images"
docker build --tag cloudward-tetragon-forwarder:local "$project_root/security-forwarder"
docker build --tag cloudward-c2-simulator:local "$project_root/demo-services/c2-simulator"
k3d image import --cluster "$CLOUDWARD_CLUSTER_NAME" \
  cloudward-tetragon-forwarder:local cloudward-c2-simulator:local

log "Installing pinned Tetragon chart ${TETRAGON_CHART_VERSION}"
helm repo add cilium https://helm.cilium.io --force-update
helm repo update cilium
kubectl apply -f "$project_root/k8s/tetragon/namespace.yaml"
helm upgrade --install tetragon cilium/tetragon \
  --namespace tetragon \
  --version "$TETRAGON_CHART_VERSION" \
  --values "$project_root/k8s/tetragon-values.yaml" \
  --wait --timeout 10m

kubectl -n tetragon create secret generic cloudward-tetragon-forwarder \
  --from-literal=webhook-secret="$webhook_secret" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k "$project_root/k8s/security-demo"
kubectl apply -k "$project_root/k8s/tetragon"
kubectl -n tetragon set env daemonset/cloudward-tetragon-forwarder \
  CLOUDWARD_SECURITY_API_URL="$security_api_url"
kubectl -n tetragon rollout status daemonset/tetragon --timeout=5m
kubectl -n tetragon rollout status daemonset/cloudward-tetragon-forwarder --timeout=5m
kubectl -n cloudward-staging rollout status deployment/cloudward-c2-simulator --timeout=3m

log "Tetragon sensor, forwarder, scoped policies, and internal simulator are installed"
