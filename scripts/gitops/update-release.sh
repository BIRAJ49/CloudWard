#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  printf '%s\n' \
    "usage: $0 VALUES_FILE ENVIRONMENT IMAGE_REPOSITORY IMAGE_DIGEST SOURCE_COMMIT SBOM_REFERENCE SCAN_STATUS VALIDATION_STATUS [ROLLBACK_DIGEST]" >&2
  exit 64
}

[[ "$#" -ge 8 && "$#" -le 9 ]] || usage

readonly values_file="$1"
readonly environment="$2"
readonly image_repository="$3"
readonly image_digest="$4"
readonly source_commit="$5"
readonly sbom_reference="$6"
readonly scan_status="$7"
readonly validation_status="$8"
readonly requested_rollback_digest="${9:-}"

command -v yq >/dev/null 2>&1 || {
  printf 'error: yq v4 is required\n' >&2
  exit 69
}

[[ -f "$values_file" && ! -L "$values_file" ]] || {
  printf 'error: values file must be a regular, non-symlink file: %s\n' "$values_file" >&2
  exit 66
}
[[ "$environment" == "staging" || "$environment" == "production" ]] || {
  printf 'error: environment must be staging or production\n' >&2
  exit 64
}
[[ "$image_repository" =~ ^ghcr\.io/[a-z0-9][a-z0-9._-]*/cloudward-[a-z0-9._-]+$ ]] || {
  printf 'error: image repository must be a CloudWard GHCR repository\n' >&2
  exit 65
}
[[ "$image_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  printf 'error: image digest must be an immutable sha256 digest\n' >&2
  exit 65
}
[[ "$source_commit" =~ ^[a-f0-9]{40}$ ]] || {
  printf 'error: source commit must be a full Git commit SHA\n' >&2
  exit 65
}
[[ "$sbom_reference" == "$image_repository@$image_digest"* ]] || {
  printf 'error: SBOM reference must be associated with the immutable image digest\n' >&2
  exit 65
}
[[ "$scan_status" == "passed" ]] || {
  printf 'error: only a release that passed the image scan may update GitOps\n' >&2
  exit 65
}
[[ "$validation_status" == "pending" || "$validation_status" == "passed" ]] || {
  printf 'error: validation status must be pending or passed\n' >&2
  exit 65
}

current_digest="$(yq -r '.cloudward-demo.image.digest // ""' "$values_file")"
readonly current_digest
current_validation="$(yq -r '.cloudward-demo.release.stagingValidation // ""' "$values_file")"
readonly current_validation
if [[ "$environment" == "staging" && -n "$current_digest" && \
      "$current_digest" != "$image_digest" && "$current_validation" != "passed" ]]; then
  printf 'error: refusing to replace an unvalidated staging release; validate or roll it back first\n' >&2
  exit 65
fi
rollback_digest="$requested_rollback_digest"
if [[ -z "$rollback_digest" ]]; then
  rollback_digest="$current_digest"
fi
if [[ -n "$rollback_digest" && ! "$rollback_digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  printf 'error: rollback digest must be empty or an immutable sha256 digest\n' >&2
  exit 65
fi
if [[ "$(yq -r '.cloudward-demo.image.requireDigest' "$values_file")" != "true" ]]; then
  printf 'error: target environment does not enforce digest-only images\n' >&2
  exit 65
fi

temporary_file="$(mktemp "${TMPDIR:-/tmp}/cloudward-values.XXXXXXXX")"
cleanup() {
  if [[ -f "$temporary_file" ]]; then
    rm -f -- "$temporary_file"
  fi
}
trap cleanup EXIT

export CLOUDWARD_IMAGE_REPOSITORY="$image_repository"
export CLOUDWARD_IMAGE_DIGEST="$image_digest"
export CLOUDWARD_SOURCE_COMMIT="$source_commit"
export CLOUDWARD_SBOM_REFERENCE="$sbom_reference"
export CLOUDWARD_SCAN_STATUS="$scan_status"
export CLOUDWARD_VALIDATION_STATUS="$validation_status"
export CLOUDWARD_ROLLBACK_DIGEST="$rollback_digest"

yq eval '
  .cloudward-demo.image.repository = strenv(CLOUDWARD_IMAGE_REPOSITORY) |
  .cloudward-demo.image.tag = "" |
  .cloudward-demo.image.digest = strenv(CLOUDWARD_IMAGE_DIGEST) |
  .cloudward-demo.image.requireDigest = true |
  .cloudward-demo.release.sourceCommit = strenv(CLOUDWARD_SOURCE_COMMIT) |
  .cloudward-demo.release.sbomReference = strenv(CLOUDWARD_SBOM_REFERENCE) |
  .cloudward-demo.release.securityScan = strenv(CLOUDWARD_SCAN_STATUS) |
  .cloudward-demo.release.stagingValidation = strenv(CLOUDWARD_VALIDATION_STATUS) |
  .cloudward-demo.release.rollbackDigest = strenv(CLOUDWARD_ROLLBACK_DIGEST)
' "$values_file" >"$temporary_file"

chmod --reference="$values_file" "$temporary_file" 2>/dev/null || true
mv -- "$temporary_file" "$values_file"
trap - EXIT

printf 'environment=%s\n' "$environment"
printf 'image=%s@%s\n' "$image_repository" "$image_digest"
printf 'rollback_digest=%s\n' "$rollback_digest"
