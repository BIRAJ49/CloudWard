#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command helm
require_command kubectl
require_command k3d
require_command git
require_command jq
require_context

project_root="$(repo_root)"
readonly project_root

log "Adding pinned upstream Helm repositories"
helm repo add cilium https://helm.cilium.io --force-update
helm repo add argo https://argoproj.github.io/argo-helm --force-update
helm repo add kyverno https://kyverno.github.io/kyverno/ --force-update
helm repo update

log "Installing full Cilium ${CILIUM_VERSION} dataplane"
if helm status cilium --namespace kube-system >/dev/null 2>&1; then
  cilium_release_status="$(helm status cilium --namespace kube-system -o json | jq -r '.info.status')"
  if [[ "$cilium_release_status" == "failed" || "$cilium_release_status" == pending-* ]]; then
    log "Removing incomplete Cilium Helm release before retry"
    helm uninstall cilium --namespace kube-system --no-hooks --wait --timeout 5m
    for attempt in $(seq 1 60); do
      if ! kubectl get namespace cilium-secrets >/dev/null 2>&1; then
        break
      fi
      if [[ "$attempt" -eq 60 ]]; then
        die "timed out waiting for cilium-secrets namespace deletion"
      fi
      sleep 2
    done
  fi
fi
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version "$CILIUM_VERSION" \
  --values "$project_root/k8s/cilium-values.yaml" \
  --rollback-on-failure --wait --timeout 15m

kubectl -n kube-system rollout status daemonset/cilium --timeout=5m
kubectl -n kube-system rollout status deployment/cilium-operator --timeout=5m
kubectl wait --for=condition=Ready nodes --all --timeout=5m

log "Creating environment namespaces"
kubectl apply -k "$project_root/k8s/namespaces"
kubectl apply -f "$project_root/k8s/cloudward-executor-rbac.yaml"
"$project_root/scripts/create-runtime-kubeconfig.sh"

log "Installing Argo CD v3.5.1 (chart ${ARGO_CD_CHART_VERSION})"
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --version "$ARGO_CD_CHART_VERSION" \
  --values "$project_root/k8s/argocd-values.yaml" \
  --wait --timeout 10m

log "Installing Kyverno v1.18.2 (chart ${KYVERNO_CHART_VERSION})"
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --version "$KYVERNO_CHART_VERSION" \
  --values "$project_root/k8s/kyverno-values.yaml" \
  --wait --timeout 10m
kubectl -n kyverno wait --for=condition=Available deployments --all --timeout=5m
kubectl apply -k "$project_root/k8s/kyverno"

if [[ -f "$project_root/demo-services/api/Dockerfile" ]]; then
  log "Building and importing the controlled demo image"
  docker build --tag cloudward-demo-api:local "$project_root/demo-services/api"
  docker build \
    --build-arg DEMO_BAD_RELEASE_ENABLED=true \
    --tag cloudward-demo-api:local-bad \
    "$project_root/demo-services/api"
  "$project_root/scripts/import-demo-image.sh" cloudward-demo-api:local
  "$project_root/scripts/import-demo-image.sh" cloudward-demo-api:local-bad
else
  die "demo Dockerfile is missing at demo-services/api/Dockerfile; cannot bootstrap a healthy GitOps workload"
fi

"$project_root/scripts/bootstrap-local-git.sh"

log "Bootstrapping the Argo CD Application; all workload resources remain Git-managed"
kubectl apply -f "$project_root/cloudward-gitops/apps/cloudward-demo.yaml"
kubectl -n argocd wait --for=jsonpath='{.status.health.status}'=Healthy \
  application/cloudward-demo --timeout=10m
kubectl -n argocd wait --for=jsonpath='{.status.sync.status}'=Synced \
  application/cloudward-demo --timeout=10m

"$project_root/scripts/install-part2-platform.sh"
"$project_root/scripts/install-tetragon.sh"

"$project_root/scripts/validate-platform.sh"
