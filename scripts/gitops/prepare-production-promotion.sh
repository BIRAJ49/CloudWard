#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 3 ]]; then
  printf 'usage: %s GITOPS_ROOT PR_BODY_FILE SOURCE_REPOSITORY\n' "$0" >&2
  exit 64
fi

readonly gitops_root="$1"
readonly pr_body_file="$2"
readonly source_repository="$3"
readonly staging_values="$gitops_root/environments/staging/values.yaml"
readonly production_values="$gitops_root/environments/production/values.yaml"

command -v yq >/dev/null 2>&1 || {
  printf 'error: yq v4 is required\n' >&2
  exit 69
}
[[ -d "$gitops_root" && ! -L "$gitops_root" ]] || {
  printf 'error: GitOps root must be a non-symlink directory\n' >&2
  exit 66
}
[[ -f "$staging_values" && -f "$production_values" ]] || {
  printf 'error: staging and production values files are required\n' >&2
  exit 66
}

repository="$(yq -r '.cloudward-demo.image.repository' "$staging_values")"
digest="$(yq -r '.cloudward-demo.image.digest' "$staging_values")"
source_commit="$(yq -r '.cloudward-demo.release.sourceCommit' "$staging_values")"
sbom_reference="$(yq -r '.cloudward-demo.release.sbomReference' "$staging_values")"
scan_status="$(yq -r '.cloudward-demo.release.securityScan' "$staging_values")"
validation_status="$(yq -r '.cloudward-demo.release.stagingValidation' "$staging_values")"
production_digest="$(yq -r '.cloudward-demo.image.digest // ""' "$production_values")"
staging_rollback_digest="$(yq -r '.cloudward-demo.release.rollbackDigest // ""' "$staging_values")"

readonly repository digest source_commit sbom_reference scan_status validation_status
readonly production_digest staging_rollback_digest

rollback_digest="$production_digest"
if [[ -z "$rollback_digest" ]]; then
  rollback_digest="$staging_rollback_digest"
fi
readonly rollback_digest

[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  printf 'error: staging is not pinned to a valid digest\n' >&2
  exit 65
}
[[ "$rollback_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  printf 'error: a known production or previously validated staging digest is required as rollback authority\n' >&2
  exit 65
}
[[ "$validation_status" == "passed" ]] || {
  printf 'error: staging validation has not passed\n' >&2
  exit 65
}
[[ "$scan_status" == "passed" ]] || {
  printf 'error: staging image scan has not passed\n' >&2
  exit 65
}
[[ "$sbom_reference" == "$repository@$digest"* ]] || {
  printf 'error: staging SBOM is not bound to the promoted digest\n' >&2
  exit 65
}
[[ "$digest" != "$production_digest" ]] || {
  printf 'error: production already references the staging digest\n' >&2
  exit 65
}

"$(dirname -- "${BASH_SOURCE[0]}")/update-release.sh" \
  "$production_values" \
  production \
  "$repository" \
  "$digest" \
  "$source_commit" \
  "$sbom_reference" \
  "$scan_status" \
  "$validation_status" \
  "$rollback_digest" >/dev/null

mkdir -p -- "$(dirname -- "$pr_body_file")"
# Markdown backticks are literal text, not shell command substitutions.
# shellcheck disable=SC2016
{
  printf '## CloudWard production promotion\n\n'
  printf '| Field | Value |\n'
  printf '| --- | --- |\n'
  printf '| Image digest | `%s@%s` |\n' "$repository" "$digest"
  printf '| Source commit | [`%s`](https://github.com/%s/commit/%s) |\n' \
    "$source_commit" "$source_repository" "$source_commit"
  printf '| Staging validation | `%s` |\n' "$validation_status"
  printf '| Security scan | `%s` |\n' "$scan_status"
  printf '| SBOM | `%s` |\n' "$sbom_reference"
  printf '| Rollback digest | `%s@%s` |\n\n' "$repository" "$rollback_digest"
  printf '### Risk notes\n\n'
  printf -- '- Production remains unchanged until this PR receives human review and is merged.\n'
  printf -- '- Argo CD will reconcile the approved Git state; no workflow performs a direct Deployment mutation.\n'
  printf -- '- Rollback is a reviewed Git change restoring the digest listed above.\n'
} >"$pr_body_file"

printf 'digest=%s\n' "$digest"
printf 'source_commit=%s\n' "$source_commit"
printf 'rollback_digest=%s\n' "$rollback_digest"
