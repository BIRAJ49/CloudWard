#!/usr/bin/env bash
# Shared constants are consumed by the scripts sourcing this library.
# shellcheck disable=SC2034

set -Eeuo pipefail

readonly CLOUDWARD_AWS_CLUSTER_NAME="${CLOUDWARD_AWS_CLUSTER_NAME:-cloudward-aws-eu-north-1}"
readonly CLOUDWARD_AWS_REGION="${CLOUDWARD_AWS_REGION:-eu-north-1}"
readonly CILIUM_AWS_CHART_VERSION="1.20.0"
readonly TETRAGON_AWS_CHART_VERSION="1.7.0"
readonly KYVERNO_AWS_CHART_VERSION="3.8.2"
readonly KARPENTER_AWS_CHART_VERSION="1.14.0"
readonly AWS_LBC_CHART_VERSION="1.15.0"
readonly AWS_LBC_APP_VERSION="v2.15.0"
readonly GATEWAY_API_VERSION="v1.2.0"
readonly KUBE_PROMETHEUS_AWS_CHART_VERSION="88.5.3"
readonly LOKI_AWS_CHART_VERSION="18.11.0"
readonly TEMPO_AWS_CHART_VERSION="2.2.4"
readonly OTEL_AWS_CHART_VERSION="0.170.0"
readonly OPENCOST_AWS_CHART_VERSION="2.2.7"
readonly CHAOS_MESH_AWS_CHART_VERSION="2.8.4"

aws_repo_root() {
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." >/dev/null 2>&1
  pwd -P
}

aws_die() {
  echo "error: $*" >&2
  exit 1
}

aws_log() {
  echo "==> $*"
}

aws_require_command() {
  command -v "$1" >/dev/null 2>&1 || aws_die "required command not found: $1"
}

aws_require_context() {
  local current_context
  current_context="$(kubectl config current-context 2>/dev/null)" ||
    aws_die "unable to read the current Kubernetes context"
  [[ "$current_context" == *"$CLOUDWARD_AWS_CLUSTER_NAME"* ]] ||
    aws_die "refusing context '$current_context'; expected a context containing '$CLOUDWARD_AWS_CLUSTER_NAME'"
}

aws_require_apply_opt_in() {
  [[ "${CLOUDWARD_AWS_PLATFORM_APPLY:-}" == "YES" ]] ||
    aws_die "set CLOUDWARD_AWS_PLATFORM_APPLY=YES to permit this explicit EKS mutation"
}

aws_require_resolved_inputs() {
  local project_root
  project_root="$(aws_repo_root)"
  if rg -n 'cloudward\\.example\\.invalid|sha256:0{64}|al2023@latest' \
    "$project_root/k8s/aws" >/dev/null; then
    aws_die "AWS platform placeholders remain; set the control-plane hostname, signed forwarder digest, and tested immutable AL2023 alias first"
  fi
}
