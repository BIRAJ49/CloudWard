#!/usr/bin/env bash

set -Eeuo pipefail

readonly api_base_url="${CLOUDWARD_API_URL:-http://localhost:8080}"
readonly dev_user="${CLOUDWARD_DEV_USER:-demo-operator}"
readonly dev_role="${CLOUDWARD_DEV_ROLE:-Operator}"
readonly max_polls="${CLOUDWARD_E2E_MAX_POLLS:-60}"
readonly poll_interval="${CLOUDWARD_E2E_POLL_INTERVAL:-2}"
readonly namespace="cloudward-staging"
readonly selector="app.kubernetes.io/name=cloudward-demo,cloudward.io/demo-target=true"
port_forward_pid=""

cleanup() {
  if [[ -n "$port_forward_pid" ]] && kill -0 "$port_forward_pid" >/dev/null 2>&1; then
    kill "$port_forward_pid"
    wait "$port_forward_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for required_command in curl jq kubectl; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf 'error: %s is required\n' "$required_command" >&2
    exit 1
  }
done

target_pods=()
while IFS= read -r pod_name; do
  [[ -n "$pod_name" ]] && target_pods+=("$pod_name")
done < <(kubectl -n "$namespace" get pods \
  --selector "$selector" \
  --field-selector status.phase=Running \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort)
[[ "${#target_pods[@]}" -ge 2 ]] || {
  printf 'error: expected at least two running controlled demo pods, found %d\n' "${#target_pods[@]}" >&2
  exit 1
}

readonly target_pod="${target_pods[0]}"
old_uid="$(kubectl -n "$namespace" get pod "$target_pod" -o jsonpath='{.metadata.uid}')"
readonly old_uid
printf 'targeting pod=%s uid=%s\n' "$target_pod" "$old_uid"

kubectl -n "$namespace" port-forward "pod/$target_pod" 18080:8080 >/dev/null 2>&1 &
port_forward_pid=$!
for _ in $(seq 1 30); do
  if curl --silent --fail http://127.0.0.1:18080/health/live >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail-with-body --silent --show-error \
  --request POST http://127.0.0.1:18080/demo/state/unhealthy >/dev/null

for _ in $(seq 1 30); do
  ready_status="$(kubectl -n "$namespace" get pod "$target_pod" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  [[ "$ready_status" == "False" ]] && break
  sleep 1
done
[[ "$ready_status" == "False" ]] || {
  printf 'error: target pod %s did not become unready\n' "$target_pod" >&2
  exit 1
}
cleanup
port_forward_pid=""

response="$(curl --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "X-CloudWard-Dev-User: $dev_user" \
  --header "X-CloudWard-Dev-Role: $dev_role" \
  --data "{\"pod_name\":\"$target_pod\"}" \
  "$api_base_url/api/v1/incidents/demo/unhealthy-pod")"

incident_id="$(jq -er '.incident_id' <<<"$response")"
state="$(jq -er '.state' <<<"$response")"
printf 'incident=%s state=%s\n' "$incident_id" "$state"

for ((poll = 1; poll <= max_polls; poll += 1)); do
  case "$state" in
    RESOLVED) break ;;
    BLOCKED|ESCALATED)
      printf '%s\n' "$response" | jq . >&2
      printf 'error: incident reached terminal failure state %s\n' "$state" >&2
      exit 1
      ;;
  esac
  sleep "$poll_interval"
  response="$(curl --fail-with-body --silent --show-error \
    --header "X-CloudWard-Dev-User: $dev_user" \
    --header "X-CloudWard-Dev-Role: $dev_role" \
    "$api_base_url/api/v1/incidents/$incident_id")"
  state="$(jq -er '.state' <<<"$response")"
  printf 'incident=%s poll=%d state=%s\n' "$incident_id" "$poll" "$state"
done

[[ "$state" == "RESOLVED" ]] || {
  printf 'error: incident %s did not resolve (last state: %s)\n' "$incident_id" "$state" >&2
  exit 1
}

detail="$(curl --fail-with-body --silent --show-error \
  --header "X-CloudWard-Dev-User: $dev_user" \
  --header "X-CloudWard-Dev-Role: $dev_role" \
  "$api_base_url/api/v1/incidents/$incident_id")"

if kubectl -n "$namespace" get pod "$target_pod" >/dev/null 2>&1; then
  current_uid="$(kubectl -n "$namespace" get pod "$target_pod" -o jsonpath='{.metadata.uid}')"
  [[ "$current_uid" != "$old_uid" ]] || {
    printf 'error: original unhealthy pod UID still exists\n' >&2
    exit 1
  }
fi
kubectl -n "$namespace" rollout status deployment/cloudward-demo --timeout=120s
ready_replicas="$(kubectl -n "$namespace" get deployment cloudward-demo -o jsonpath='{.status.readyReplicas}')"
[[ "$ready_replicas" -ge 2 ]] || { printf 'error: ready replicas=%s\n' "$ready_replicas" >&2; exit 1; }

replacement_uids="$(kubectl -n "$namespace" get pods --selector "$selector" -o jsonpath='{range .items[*]}{.metadata.uid}{"\n"}{end}')"
grep -Fvxq "$old_uid" <<<"$replacement_uids" || {
  printf 'error: no replacement pod UID was observed\n' >&2
  exit 1
}

for expected_audit_event in ACTION_EXECUTED VERIFICATION_COMPLETED INCIDENT_RESOLVED; do
  jq -e --arg event "$expected_audit_event" \
    'any(.audit_events[]; .event_type == $event)' <<<"$detail" >/dev/null || {
    printf 'error: missing audit event %s\n' "$expected_audit_event" >&2
    exit 1
  }
done
jq -e '.actions | length > 0' <<<"$detail" >/dev/null
jq -e '.policy_decisions | length > 0' <<<"$detail" >/dev/null
jq -e 'any(.events[]; .event_type == "STATE_CHANGED" and .to_state == "RESOLVED")' \
  <<<"$detail" >/dev/null

printf '%s\n' "$detail" | jq '{id, state, risk_score, runbook_id, retry_count}'
printf 'E2E passed: original pod %s was remediated and incident %s resolved\n' \
  "$target_pod" "$incident_id"
