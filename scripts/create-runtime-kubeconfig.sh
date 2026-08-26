#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context

project_root="$(repo_root)"
readonly project_root
readonly output_dir="$project_root/.k3d"
readonly output_file="$output_dir/cloudward-kubeconfig.yaml"
readonly service_account="cloudward-executor"
readonly namespace="cloudward-staging"
readonly api_server="https://host.docker.internal:6550"
cluster_ca="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
readonly cluster_ca

mkdir -p "$output_dir"
chmod 700 "$output_dir"

# The requested token is time-bounded and only authenticates the namespace-
# scoped Role in k8s/cloudward-executor-rbac.yaml. Regenerate after expiration.
runtime_token="$(kubectl -n "$namespace" create token "$service_account" --duration=24h)"

umask 077
{
  printf '%s\n' 'apiVersion: v1' 'kind: Config' 'clusters:'
  printf '%s\n' '- name: cloudward-local'
  printf '%s\n' '  cluster:'
  printf '    certificate-authority-data: %s\n' "$cluster_ca"
  printf '    server: %s\n' "$api_server"
  printf '%s\n' '    tls-server-name: k3d-cloudward-server-0'
  printf '%s\n' 'users:' '- name: cloudward-executor' '  user:'
  printf '    token: %s\n' "$runtime_token"
  printf '%s\n' 'contexts:' '- name: k3d-cloudward' '  context:'
  printf '%s\n' '    cluster: cloudward-local' '    namespace: cloudward-staging' '    user: cloudward-executor'
  printf '%s\n' 'current-context: k3d-cloudward'
} >"$output_file"

chmod 600 "$output_file"
log "Wrote time-bounded, namespace-scoped runtime kubeconfig: $output_file"
