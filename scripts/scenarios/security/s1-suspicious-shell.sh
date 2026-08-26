#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

pod="$(demo_pod)"
log "S1 setup: target is the single controlled pod $pod"
trigger_demo_path "$pod" "/demo/security/suspicious-shell"
event_id="$(wait_for_security_event SUSPICIOUS_PROCESS "$pod")"
log "S1 detected as security event $event_id"
apply_and_verify_containment "$event_id"
remove_and_verify_containment "$event_id"
log "S1 cleanup verified; no external endpoint or usable remote shell was created"

