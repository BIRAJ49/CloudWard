#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command k3d

if ! cluster_exists; then
  log "Cluster '$CLOUDWARD_CLUSTER_NAME' does not exist; nothing to destroy"
  exit 0
fi

log "Deleting the dedicated k3d cluster '$CLOUDWARD_CLUSTER_NAME'"

# Delete the short-lived bearer-token kubeconfig first so it is not left behind
# even if Docker is slow or k3d deletion is interrupted.
project_root="$(repo_root)"
runtime_kubeconfig="$project_root/.k3d/cloudward-kubeconfig.yaml"
if [[ -f "$runtime_kubeconfig" ]]; then
  find "$runtime_kubeconfig" -delete
  log "Removed generated runtime kubeconfig token; it is unrecoverable and invalid after cluster deletion"
fi

k3d cluster delete "$CLOUDWARD_CLUSTER_NAME"

if [[ -d "$project_root/.k3d" ]] && [[ -z "$(find "$project_root/.k3d" -mindepth 1 -print -quit)" ]]; then
  rmdir "$project_root/.k3d"
fi
log "Cluster, in-cluster Git snapshot, and all associated k3d resources were deleted"
