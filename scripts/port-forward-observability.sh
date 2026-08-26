#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context

component="${1:-grafana}"
case "$component" in
  grafana)
    target=service/kube-prometheus-stack-grafana
    mapping=3001:80
    ;;
  prometheus)
    target=service/kube-prometheus-stack-prometheus
    mapping=9090:9090
    ;;
  alertmanager)
    target=service/kube-prometheus-stack-alertmanager
    mapping=9093:9093
    ;;
  loki)
    target=service/loki
    mapping=3100:3100
    ;;
  tempo)
    target=service/tempo
    mapping=3200:3200
    ;;
  *)
    die "unknown component '$component'; choose grafana, prometheus, alertmanager, loki, or tempo"
    ;;
esac

log "Forwarding $component at http://127.0.0.1:${mapping%%:*}; press Ctrl-C to stop"
exec kubectl -n observability port-forward "$target" "$mapping"
