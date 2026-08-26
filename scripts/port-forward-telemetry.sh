#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context

pids=()
cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

forward() {
  local target="$1"
  local mapping="$2"
  kubectl -n observability port-forward --address 127.0.0.1 "$target" "$mapping" >/dev/null &
  pids+=("$!")
}

forward service/kube-prometheus-stack-prometheus 9090:9090
forward service/loki 3100:3100
forward service/tempo 3200:3200
kubectl -n opencost port-forward --address 127.0.0.1 service/opencost 9003:9003 >/dev/null &
pids+=("$!")

log "Telemetry bridge active: Prometheus :9090, Loki :3100, Tempo :3200, OpenCost :9003"
log "Keep this process running while executing Incident Lab workflows; press Ctrl-C to stop"
wait "${pids[@]}"
