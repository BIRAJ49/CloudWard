#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
  printf 'usage: %s IMAGE_REPOSITORY IMAGE_DIGEST\n' "$0" >&2
  exit 64
fi

readonly image_repository="$1"
readonly image_digest="$2"
readonly expected_image="$image_repository@$image_digest"
readonly expected_context="${EXPECTED_KUBE_CONTEXT:-k3d-cloudward}"
readonly namespace="cloudward-staging"
readonly application="cloudward-staging"
readonly deployment="cloudward-staging-cloudward-demo"

for command_name in kubectl curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'error: required command not found: %s\n' "$command_name" >&2
    exit 69
  }
done
[[ "$image_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  printf 'error: expected an immutable sha256 digest\n' >&2
  exit 65
}
[[ "$(kubectl config current-context)" == "$expected_context" ]] || {
  printf 'error: refusing context %s; expected %s\n' \
    "$(kubectl config current-context)" "$expected_context" >&2
  exit 77
}

kubectl -n argocd wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/$application" --timeout=10m
kubectl -n argocd wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/$application" --timeout=10m
kubectl -n "$namespace" rollout status "deployment/$deployment" --timeout=5m

deployed_image="$(kubectl -n "$namespace" get "deployment/$deployment" \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')"
readonly deployed_image
[[ "$deployed_image" == "$expected_image" ]] || {
  printf 'error: deployed image %s does not equal %s\n' "$deployed_image" "$expected_image" >&2
  exit 1
}

port_forward_log="$(mktemp "${TMPDIR:-/tmp}/cloudward-port-forward.XXXXXXXX")"
kubectl -n "$namespace" port-forward "service/$deployment" 18080:80 \
  >"$port_forward_log" 2>&1 &
port_forward_pid="$!"
cleanup() {
  kill "$port_forward_pid" >/dev/null 2>&1 || true
  wait "$port_forward_pid" >/dev/null 2>&1 || true
  rm -f -- "$port_forward_log"
}
trap cleanup EXIT

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 2 \
    http://127.0.0.1:18080/health/ready >/dev/null; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    printf 'error: staging health endpoint did not become ready\n' >&2
    exit 1
  fi
  sleep 1
done

curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:18080/health/ready >/dev/null
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:18080/demo/state >/dev/null

printf 'staging validation passed for %s\n' "$expected_image"
