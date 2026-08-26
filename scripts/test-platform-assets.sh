#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command docker
require_command helm
require_command jq
require_command kubectl
require_command shellcheck

project_root="$(repo_root)"
readonly project_root
render_root="$(mktemp -d "${TMPDIR:-/tmp}/cloudward-render.XXXXXXXX")"
readonly render_root

log "Checking shell scripts"
shellcheck -x -P "$project_root/scripts" "$project_root"/scripts/*.sh

log "Running OPA ${OPA_VERSION} policy tests"
docker run --rm \
  -v "$project_root/policies/opa:/policies:ro" \
  "openpolicyagent/opa:${OPA_VERSION}" test -v /policies

log "Linting and rendering the demo Helm chart for every environment"
helm lint "$project_root/helm/cloudward-demo" --strict
readonly test_release_digest="sha256:1111111111111111111111111111111111111111111111111111111111111111"
for environment in local staging production; do
  digest_arguments=()
  if [[ "$environment" != "local" ]]; then
    digest_arguments=(--set-string "image.digest=$test_release_digest")
  fi
  helm lint "$project_root/helm/cloudward-demo" \
    --values "$project_root/helm/cloudward-demo/values-${environment}.yaml" \
    "${digest_arguments[@]}" --strict
  helm template cloudward-demo "$project_root/helm/cloudward-demo" \
    --namespace "cloudward-${environment/local/staging}" \
    --values "$project_root/helm/cloudward-demo/values-${environment}.yaml" \
    "${digest_arguments[@]}" \
    >"$render_root/${environment}.yaml"
done

log "Reproducing Argo CD's exact ephemeral checkout and local chart dependency"
mkdir -p "$render_root/gitops/helm"
cp -R "$project_root/cloudward-gitops/." "$render_root/gitops/cloudward-gitops"
cp -R "$project_root/helm/cloudward-demo" "$render_root/gitops/helm/cloudward-demo"
helm dependency build "$render_root/gitops/cloudward-gitops/environments/local" >/dev/null
helm template cloudward-local "$render_root/gitops/cloudward-gitops/environments/local" \
  --namespace cloudward-staging >"$render_root/gitops-local.yaml"
grep -Fq 'cloudward.io/demo-target: "true"' "$render_root/gitops-local.yaml"

log "Rendering static Kustomize resources with client-side kubectl"
kubectl kustomize "$project_root/k8s/namespaces" >"$render_root/namespaces.yaml"
kubectl kustomize "$project_root/k8s/kyverno" >"$render_root/kyverno.yaml"

log "Rendering pinned Part 2 observability and Chaos Mesh assets"
"$project_root/scripts/render-part2-platform.sh" "$render_root/part2"

log "Asset validation passed; rendered files are in $render_root"
