#!/usr/bin/env bash
set -euo pipefail

project_dir="${CLOUDWARD_PROJECT_DIR:-/opt/cloudward}"
backup_dir="/var/backups/cloudward/postgres"
backup_file="${1:-}"
if [[ "${CLOUDWARD_RESTORE_CONFIRM:-}" != "RESTORE_CLOUDWARD_POSTGRES" ]]; then
  printf 'Refusing destructive restore. Set CLOUDWARD_RESTORE_CONFIRM=RESTORE_CLOUDWARD_POSTGRES.\n' >&2
  exit 64
fi
if [[ "$project_dir" != "/opt/cloudward" || -z "$backup_file" || ! -f "$backup_file" ]]; then
  printf 'Provide an existing CloudWard dump file.\n' >&2
  exit 66
fi

resolved_file="$(realpath "$backup_file")"
case "$resolved_file" in
  "$backup_dir"/*.dump) ;;
  *) printf 'Backup must be under %s.\n' "$backup_dir" >&2; exit 64 ;;
esac

cd "$project_dir"
compose=(docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml)
"${compose[@]}" stop api worker
"${compose[@]}" exec -T postgres pg_restore \
  --username cloudward --dbname cloudward --clean --if-exists --exit-on-error <"$resolved_file"
"${compose[@]}" up -d api worker
printf 'Restore completed from %s. Perform the documented health and integrity checks.\n' "$resolved_file"
