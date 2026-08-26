#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context

kubectl -n tetragon rollout status daemonset/tetragon --timeout=2m
kubectl -n tetragon rollout status daemonset/cloudward-tetragon-forwarder --timeout=2m
kubectl -n cloudward-staging get tracingpoliciesnamespaced \
  cloudward-s1-unexpected-shell cloudward-s2-unexpected-egress cloudward-s3-privilege-attempt \
  >/dev/null
kubectl -n cloudward-staging get service cloudward-c2-simulator >/dev/null

log "Tetragon runtime-security components are healthy; scenario scripts prove event flow"
