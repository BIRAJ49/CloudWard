#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=../../lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/../../lib.sh"

require_command curl
require_command jq
require_command kubectl
require_context

readonly SECURITY_API_BASE="${CLOUDWARD_API_URL:-http://127.0.0.1:8080/api/v1}"
readonly SECURITY_TIMEOUT_SECONDS="${SECURITY_SCENARIO_TIMEOUT_SECONDS:-120}"

demo_pod() {
  local pod
  pod="$(kubectl -n cloudward-staging get pod \
    -l cloudward.io/demo-target=true \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}')"
  [[ -n "$pod" ]] || die "no running labeled demo pod is available"
  printf '%s\n' "$pod"
}

trigger_demo_path() {
  local pod="$1"
  local path="$2"
  kubectl get --raw "/api/v1/namespaces/cloudward-staging/pods/${pod}:8080/proxy${path}" >/dev/null
}

wait_for_security_event() {
  local category="$1"
  local pod="$2"
  local deadline=$((SECONDS + SECURITY_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    event_id="$(curl --fail --silent --show-error \
      -H 'X-CloudWard-Dev-User: incident-lab' \
      -H 'X-CloudWard-Dev-Role: Admin' \
      "$SECURITY_API_BASE/security/events?event_type=$category&limit=20" |
      jq -r --arg pod "$pod" '[.[] | select(.pod == $pod)][0].id // empty')"
    if [[ -n "$event_id" ]]; then
      printf '%s\n' "$event_id"
      return
    fi
    sleep 2
  done
  die "timed out waiting for normalized $category event"
}

apply_and_verify_containment() {
  local event_id="$1"
  curl --fail --silent --show-error -X POST \
    -H 'X-CloudWard-Dev-User: incident-lab' \
    -H 'X-CloudWard-Dev-Role: Admin' \
    "$SECURITY_API_BASE/security/events/$event_id/containment/apply" |
    jq -e '.status == "CONTAINED" and .verification.success == true' >/dev/null
}

remove_and_verify_containment() {
  local event_id="$1"
  curl --fail --silent --show-error -X POST \
    -H 'X-CloudWard-Dev-User: incident-lab' \
    -H 'X-CloudWard-Dev-Role: Admin' \
    "$SECURITY_API_BASE/security/events/$event_id/containment/remove" |
    jq -e '.status == "REMOVED" and .verification.success == true' >/dev/null
}

