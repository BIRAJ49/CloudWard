#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command docker
require_command k3d
require_command kubectl

docker info >/dev/null 2>&1 || die "Docker daemon is not reachable"

if cluster_exists; then
  die "cluster '$CLOUDWARD_CLUSTER_NAME' already exists; destroy it first or run bootstrap"
fi

log "Creating k3d cluster '$CLOUDWARD_CLUSTER_NAME' with Cilium as its only CNI"
k3d cluster create "$CLOUDWARD_CLUSTER_NAME" \
  --image "$K3S_IMAGE" \
  --servers 1 \
  --agents 1 \
  --api-port 127.0.0.1:6550 \
  --port '127.0.0.1:19418:30918@server:0' \
  --k3s-arg '--flannel-backend=none@server:*' \
  --k3s-arg '--disable-network-policy@server:*' \
  --k3s-arg '--disable=traefik@server:*' \
  --k3s-arg '--disable=servicelb@server:*' \
  --k3s-arg '--disable=metrics-server@server:*' \
  --k3s-arg '--disable=local-storage@server:*' \
  --wait=false

log "Waiting for the Kubernetes API to become available"
for attempt in $(seq 1 60); do
  if k3d kubeconfig get "$CLOUDWARD_CLUSTER_NAME" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    die "timed out waiting for cluster kubeconfig"
  fi
  sleep 2
done

k3d kubeconfig merge "$CLOUDWARD_CLUSTER_NAME" --kubeconfig-switch-context >/dev/null
kubectl config use-context "$CLOUDWARD_KUBECONFIG_CONTEXT" >/dev/null
require_context

log "Cluster created. Nodes remain NotReady until scripts/cluster-bootstrap.sh installs Cilium."
