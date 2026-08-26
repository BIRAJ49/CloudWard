#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context

project_root="$(repo_root)"
readonly project_root

log "Applying the scoped CloudWard signature-verification policy"
kubectl apply -k "$project_root/k8s/kyverno"

log "Installing read-only Argo CD drift visibility"
kubectl apply -k "$project_root/k8s/gitops-observability"

log "Part 3 supply-chain cluster controls installed"
log "Remote staging/production Applications remain explicit; configure the GitOps repository first"
