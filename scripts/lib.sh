#!/usr/bin/env bash

# shellcheck disable=SC2034 # Constants are consumed by scripts that source this library.
set -Eeuo pipefail

readonly CLOUDWARD_CLUSTER_NAME="${CLOUDWARD_CLUSTER_NAME:-cloudward}"
readonly CLOUDWARD_KUBECONFIG_CONTEXT="k3d-${CLOUDWARD_CLUSTER_NAME}"
readonly K3S_IMAGE="rancher/k3s:v1.35.7-k3s1"
readonly CILIUM_VERSION="1.20.0"
readonly ARGO_CD_CHART_VERSION="10.3.3"
readonly KYVERNO_CHART_VERSION="3.8.2"
readonly OPA_VERSION="1.19.0"
readonly KUBE_PROMETHEUS_STACK_CHART_VERSION="88.5.3"
readonly LOKI_CHART_VERSION="18.11.0"
readonly TEMPO_CHART_VERSION="2.2.4"
readonly OTEL_COLLECTOR_CHART_VERSION="0.170.0"
readonly CHAOS_MESH_CHART_VERSION="2.8.4"
readonly TETRAGON_CHART_VERSION="1.7.0"
readonly OPENCOST_CHART_VERSION="2.2.7"

repo_root() {
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1
  pwd -P
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '==> %s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_context() {
  local current_context
  current_context="$(kubectl config current-context 2>/dev/null || true)"
  [[ "$current_context" == "$CLOUDWARD_KUBECONFIG_CONTEXT" ]] ||
    die "refusing to operate on context '$current_context'; expected '$CLOUDWARD_KUBECONFIG_CONTEXT'"
}

cluster_exists() {
  k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -Fxq "$CLOUDWARD_CLUSTER_NAME"
}
