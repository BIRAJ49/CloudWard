#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command helm
require_command kubectl
require_command openssl
require_context

project_root="$(repo_root)"
readonly project_root

env_value() {
  local key="$1"
  local env_file="$project_root/.env"
  [[ -f "$env_file" ]] || return 0
  awk -v key="$key" 'index($0, key "=") == 1 {sub("^[^=]*=", ""); print; exit}' "$env_file"
}

webhook_token="${ALERTMANAGER_WEBHOOK_TOKEN:-}"
if [[ -z "$webhook_token" ]]; then
  webhook_token="$(env_value ALERTMANAGER_WEBHOOK_TOKEN)"
fi
[[ ${#webhook_token} -ge 32 ]] ||
  die "ALERTMANAGER_WEBHOOK_TOKEN must be a non-placeholder value of at least 32 characters (export it or set it in .env)"
[[ "$webhook_token" != replace-me* ]] ||
  die "ALERTMANAGER_WEBHOOK_TOKEN is still a placeholder"

log "Creating isolated Part 2 namespaces"
kubectl apply -k "$project_root/k8s/namespaces"

log "Reconciling Alertmanager webhook credentials without writing them to the repository"
kubectl -n observability create secret generic cloudward-alertmanager-webhook \
  --from-literal=token="$webhook_token" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
unset webhook_token

grafana_password="${CLOUDWARD_GRAFANA_ADMIN_PASSWORD:-}"
if [[ -n "$grafana_password" ]]; then
  [[ ${#grafana_password} -ge 16 ]] ||
    die "CLOUDWARD_GRAFANA_ADMIN_PASSWORD must be at least 16 characters"
elif ! kubectl -n observability get secret cloudward-grafana-admin >/dev/null 2>&1; then
  grafana_password="$(openssl rand -base64 24)"
fi
if [[ -n "$grafana_password" ]]; then
  kubectl -n observability create secret generic cloudward-grafana-admin \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="$grafana_password" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  unset grafana_password
fi

log "Adding official Helm repositories"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana-community https://grafana-community.github.io/helm-charts --force-update
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts --force-update
helm repo add chaos-mesh https://charts.chaos-mesh.org --force-update
helm repo update

log "Installing Prometheus, Alertmanager, and Grafana chart ${KUBE_PROMETHEUS_STACK_CHART_VERSION}"
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --version "$KUBE_PROMETHEUS_STACK_CHART_VERSION" \
  --values "$project_root/k8s/observability/kube-prometheus-stack-values.yaml" \
  --rollback-on-failure --wait --timeout 15m

log "Installing single-binary Loki chart ${LOKI_CHART_VERSION}"
helm upgrade --install loki grafana-community/loki \
  --namespace observability \
  --version "$LOKI_CHART_VERSION" \
  --values "$project_root/k8s/observability/loki-values.yaml" \
  --rollback-on-failure --wait --timeout 10m

log "Installing single-binary Tempo chart ${TEMPO_CHART_VERSION}"
helm upgrade --install tempo grafana-community/tempo \
  --namespace observability \
  --version "$TEMPO_CHART_VERSION" \
  --values "$project_root/k8s/observability/tempo-values.yaml" \
  --rollback-on-failure --wait --timeout 10m

log "Installing OpenTelemetry Collector chart ${OTEL_COLLECTOR_CHART_VERSION}"
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  --namespace observability \
  --version "$OTEL_COLLECTOR_CHART_VERSION" \
  --values "$project_root/k8s/observability/otel-collector-values.yaml" \
  --rollback-on-failure --wait --timeout 10m

log "Applying CloudWard scrape targets, alert routes, rules, and dashboards"
kubectl apply -k "$project_root/k8s/observability"

log "Installing Chaos Mesh chart ${CHAOS_MESH_CHART_VERSION} with the k3s containerd socket"
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --version "$CHAOS_MESH_CHART_VERSION" \
  --values "$project_root/k8s/chaos-mesh/values.yaml" \
  --rollback-on-failure --wait --timeout 15m

log "Part 2 platform installed. Run scripts/validate-part2-platform.sh only after the instrumented demo and control plane are running."
