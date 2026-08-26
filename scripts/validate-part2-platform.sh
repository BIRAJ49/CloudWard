#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command curl
require_command helm
require_command jq
require_command kubectl
require_context

log "Checking pinned Helm releases"
for release_namespace in \
  "observability kube-prometheus-stack" \
  "observability loki" \
  "observability tempo" \
  "observability otel-collector" \
  "chaos-mesh chaos-mesh"; do
  read -r namespace release <<<"$release_namespace"
  [[ "$(helm status "$release" --namespace "$namespace" -o json | jq -r '.info.status')" == "deployed" ]]
done

log "Waiting for all Part 2 workload controllers"
while IFS= read -r controller; do
  kubectl -n observability rollout status "$controller" --timeout=5m
done < <(kubectl -n observability get deployment,statefulset,daemonset -o name)
while IFS= read -r controller; do
  kubectl -n chaos-mesh rollout status "$controller" --timeout=5m
done < <(kubectl -n chaos-mesh get deployment,statefulset,daemonset -o name)

kubectl get prometheusrule -n observability cloudward-reliability cloudward-control-plane >/dev/null
kubectl get alertmanagerconfig -n observability cloudward-webhook >/dev/null
kubectl get servicemonitor -n observability cloudward-demo >/dev/null

forward_pids=()
cleanup() {
  local pid
  for pid in "${forward_pids[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

start_forward() {
  local target="$1"
  local mapping="$2"
  kubectl -n observability port-forward "$target" "$mapping" >/dev/null 2>&1 &
  forward_pids+=("$!")
}

start_forward service/kube-prometheus-stack-prometheus 19090:9090
start_forward service/kube-prometheus-stack-alertmanager 19093:9093
start_forward service/kube-prometheus-stack-grafana 13000:80
start_forward service/loki 13100:3100
start_forward service/tempo 13200:3200

for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:19090/-/ready >/dev/null &&
    curl --fail --silent http://127.0.0.1:19093/-/ready >/dev/null &&
    curl --fail --silent http://127.0.0.1:13000/api/health >/dev/null &&
    curl --fail --silent http://127.0.0.1:13100/ready >/dev/null &&
    curl --fail --silent http://127.0.0.1:13200/ready >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || die "timed out waiting for local observability API forwards"
  sleep 2
done

log "Checking that Prometheus actually scrapes the demo workload"
curl --fail --silent http://127.0.0.1:19090/api/v1/targets |
  jq -e '.data.activeTargets | any(.labels.job | contains("cloudward-demo")) and any(select(.labels.job | contains("cloudward-demo")) | .health == "up")' >/dev/null

log "Checking that Loki contains staging logs"
curl --fail --silent --get http://127.0.0.1:13100/loki/api/v1/query \
  --data-urlencode 'query={k8s_namespace_name="cloudward-staging"}' \
  --data-urlencode 'limit=1' |
  jq -e '.status == "success" and (.data.result | length) > 0' >/dev/null

log "Checking that Tempo contains at least one trace and Loki can find its trace ID"
trace_id="$(curl --fail --silent --get http://127.0.0.1:13200/api/search \
  --data-urlencode 'limit=1' | jq -r '.traces[0].traceID // empty')"
[[ "$trace_id" =~ ^[0-9a-fA-F]{16,32}$ ]] || die "Tempo returned no trace for correlation validation"
curl --fail --silent --get http://127.0.0.1:13100/loki/api/v1/query \
  --data-urlencode "query={k8s_namespace_name=\"cloudward-staging\"} |= \"$trace_id\"" \
  --data-urlencode 'limit=1' |
  jq -e '.status == "success" and (.data.result | length) > 0' >/dev/null

log "Part 2 observability health, ingestion, and trace/log correlation checks passed"
