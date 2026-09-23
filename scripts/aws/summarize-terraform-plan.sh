#!/usr/bin/env bash
set -euo pipefail

plan_file="${1:-}"
if [[ -z "$plan_file" || ! -f "$plan_file" ]]; then
  printf 'usage: %s <terraform-plan-file>\n' "$0" >&2
  exit 64
fi

plan_json="$(mktemp)"
trap 'rm -f "$plan_json"' EXIT
terraform show -json "$plan_file" >"$plan_json"

printf '## Terraform plan summary\n\n'
printf '| Change | Count |\n| --- | ---: |\n'
for action in create update delete replace no-op; do
  count="$(jq --arg action "$action" '[.resource_changes[]? | select(
    ($action == "create" and .change.actions == ["create"]) or
    ($action == "update" and .change.actions == ["update"]) or
    ($action == "delete" and .change.actions == ["delete"]) or
    ($action == "replace" and ((.change.actions == ["delete","create"]) or (.change.actions == ["create","delete"]))) or
    ($action == "no-op" and .change.actions == ["no-op"])
  )] | length' "$plan_json")"
  printf '| %s | %s |\n' "$action" "$count"
done

printf '\n### Affected resource types\n\n'
jq -r '[.resource_changes[]? | select(.change.actions != ["no-op"]) | .type] | unique[] | "- `" + . + "`"' "$plan_json"
printf '\nThis summary intentionally excludes attribute values because plans can contain sensitive data. Review the encrypted plan artifact in an authorized environment before approval.\n'
