#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command helm
require_command jq
require_command kubectl

project_root="$(repo_root)"
readonly project_root
render_root="${1:-$(mktemp -d "${TMPDIR:-/tmp}/cloudward-part2-render.XXXXXXXX")}"
readonly render_root
mkdir -p "$render_root/cache"

repo_config="$render_root/repositories.yaml"
repo_cache="$render_root/cache"

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts \
  --repository-config "$repo_config" --repository-cache "$repo_cache" >/dev/null
helm repo add grafana-community https://grafana-community.github.io/helm-charts \
  --repository-config "$repo_config" --repository-cache "$repo_cache" >/dev/null
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts \
  --repository-config "$repo_config" --repository-cache "$repo_cache" >/dev/null
helm repo add chaos-mesh https://charts.chaos-mesh.org \
  --repository-config "$repo_config" --repository-cache "$repo_cache" >/dev/null

render_chart() {
  local release="$1"
  local chart="$2"
  local version="$3"
  local namespace="$4"
  local values="$5"
  local output="$6"
  helm template "$release" "$chart" \
    --namespace "$namespace" \
    --version "$version" \
    --values "$values" \
    --include-crds \
    --repository-config "$repo_config" \
    --repository-cache "$repo_cache" >"$render_root/$output"
}

render_chart kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  "$KUBE_PROMETHEUS_STACK_CHART_VERSION" observability \
  "$project_root/k8s/observability/kube-prometheus-stack-values.yaml" prometheus-stack.yaml
render_chart loki grafana-community/loki "$LOKI_CHART_VERSION" observability \
  "$project_root/k8s/observability/loki-values.yaml" loki.yaml
render_chart tempo grafana-community/tempo "$TEMPO_CHART_VERSION" observability \
  "$project_root/k8s/observability/tempo-values.yaml" tempo.yaml
render_chart otel-collector open-telemetry/opentelemetry-collector \
  "$OTEL_COLLECTOR_CHART_VERSION" observability \
  "$project_root/k8s/observability/otel-collector-values.yaml" otel-collector.yaml
render_chart chaos-mesh chaos-mesh/chaos-mesh "$CHAOS_MESH_CHART_VERSION" chaos-mesh \
  "$project_root/k8s/chaos-mesh/values.yaml" chaos-mesh.yaml

kubectl kustomize "$project_root/k8s/observability" >"$render_root/cloudward-observability.yaml"
kubectl kustomize "$project_root/k8s/kyverno" >"$render_root/cloudward-kyverno.yaml"
kubectl kustomize "$project_root/k8s/namespaces" >"$render_root/cloudward-namespaces.yaml"

for dashboard in "$project_root"/k8s/observability/dashboards/*.yaml; do
  awk 'found {sub(/^    /, ""); print} /\.json: \|$/ {found=1}' "$dashboard" |
    jq -e '.uid and .title and (.panels | length > 0)' >/dev/null
done

for scenario in "$project_root"/k8s/chaos-mesh/scenarios/*.yaml; do
  grep -Fq 'namespace: cloudward-staging' "$scenario"
  grep -Fq 'cloudward.io/demo-target: "true"' "$scenario"
  if grep -Eq 'cloudward-production|kube-system|argocd|observability|kyverno|tetragon|chaos-mesh' "$scenario"; then
    die "forbidden chaos target found in $scenario"
  fi
done

log "Part 2 platform assets rendered successfully in $render_root"
