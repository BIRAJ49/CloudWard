#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

pod="$(demo_pod)"
log "S2 setup: verifying only the internal simulator is reachable"
trigger_demo_path "$pod" "/demo/security/egress-probe"
trigger_demo_path "$pod" "/demo/security/unexpected-egress"
event_id="$(wait_for_security_event UNEXPECTED_EGRESS "$pod")"
log "S2 detected as security event $event_id"
apply_and_verify_containment "$event_id"
remove_and_verify_containment "$event_id"
log "S2 cleanup verified; internal simulator connectivity was restored"

