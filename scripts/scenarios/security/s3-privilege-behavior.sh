#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

pod="$(demo_pod)"
log "S3 setup: triggering a benign denied read of /proc/1/mem"
trigger_demo_path "$pod" "/demo/security/privilege-attempt"
event_id="$(wait_for_security_event PRIVILEGE_BEHAVIOR "$pod")"
log "S3 detected as security event $event_id"
apply_and_verify_containment "$event_id"
remove_and_verify_containment "$event_id"
log "S3 cleanup verified; no exploit, escape, or host modification was attempted"
