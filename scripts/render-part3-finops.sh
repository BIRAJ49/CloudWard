#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command helm

project_root="$(repo_root)"
readonly project_root
render_root="${1:-$(mktemp -d "${TMPDIR:-/tmp}/cloudward-part3-finops.XXXXXXXX")}"
readonly render_root
mkdir -p "$render_root/cache"

repo_config="$render_root/repositories.yaml"
repo_cache="$render_root/cache"
helm repo add opencost https://opencost.github.io/opencost-helm-chart \
  --repository-config "$repo_config" --repository-cache "$repo_cache" >/dev/null

helm template opencost opencost/opencost \
  --namespace opencost \
  --version "$OPENCOST_CHART_VERSION" \
  --values "$project_root/k8s/opencost/values.yaml" \
  --include-crds \
  --repository-config "$repo_config" \
  --repository-cache "$repo_cache" >"$render_root/opencost.yaml"

log "Part 3 OpenCost assets rendered in $render_root"
