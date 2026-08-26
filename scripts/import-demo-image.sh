#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command docker
require_command k3d
cluster_exists || die "cluster '$CLOUDWARD_CLUSTER_NAME' does not exist"

readonly image_name="${1:-cloudward-demo-api:local}"
docker image inspect "$image_name" >/dev/null 2>&1 || die "local image not found: $image_name"

log "Importing '$image_name' into '$CLOUDWARD_CLUSTER_NAME'"
k3d image import "$image_name" --cluster "$CLOUDWARD_CLUSTER_NAME"
