#!/usr/bin/env bash

set -Eeuo pipefail

command -v yq >/dev/null 2>&1 || {
  printf 'error: yq v4 is required\n' >&2
  exit 69
}

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/cloudward-gitops-test.XXXXXXXX")"
cleanup() {
  if [[ -d "$test_root" && "$test_root" == "${TMPDIR:-/tmp}"/cloudward-gitops-test.* ]]; then
    find "$test_root" -depth -delete
  fi
}
trap cleanup EXIT

cp -R "$project_root/cloudward-gitops/environments" "$test_root/environments"
readonly values="$test_root/environments/staging/values.yaml"
readonly digest_a="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
readonly digest_b="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
readonly source_a="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
readonly source_b="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
readonly repository="ghcr.io/biraj49/cloudward-demo-api"

if "$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" latest "$source_a" \
  "$repository:latest#attestation=cyclonedx" passed pending >/dev/null 2>&1; then
  printf 'error: mutable tag was accepted as release authority\n' >&2
  exit 1
fi

"$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" "$digest_a" "$source_a" \
  "$repository@$digest_a#attestation=cyclonedx" passed pending >/dev/null

if "$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" "$digest_b" "$source_b" \
  "$repository@$digest_b#attestation=cyclonedx" passed pending >/dev/null 2>&1; then
  printf 'error: an unvalidated staging release was overwritten\n' >&2
  exit 1
fi

"$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" "$digest_a" "$source_a" \
  "$repository@$digest_a#attestation=cyclonedx" passed passed >/dev/null
"$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" "$digest_b" "$source_b" \
  "$repository@$digest_b#attestation=cyclonedx" passed pending >/dev/null
"$project_root/scripts/gitops/update-release.sh" \
  "$values" staging "$repository" "$digest_b" "$source_b" \
  "$repository@$digest_b#attestation=cyclonedx" passed passed "$digest_a" >/dev/null

"$project_root/scripts/gitops/prepare-production-promotion.sh" \
  "$test_root" "$test_root/promotion.md" biraj49/CloudWard >/dev/null

[[ "$(yq -r '.cloudward-demo.image.digest' "$test_root/environments/production/values.yaml")" == "$digest_b" ]]
[[ "$(yq -r '.cloudward-demo.release.rollbackDigest' "$test_root/environments/production/values.yaml")" == "$digest_a" ]]
grep -Fq "$repository@$digest_b" "$test_root/promotion.md"
grep -Fq "$repository@$digest_a" "$test_root/promotion.md"

printf 'GitOps promotion asset tests passed\n'
