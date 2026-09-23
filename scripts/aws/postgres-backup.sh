#!/usr/bin/env bash
set -euo pipefail

project_dir="${CLOUDWARD_PROJECT_DIR:-/opt/cloudward}"
backup_dir="${CLOUDWARD_BACKUP_DIR:-/var/backups/cloudward/postgres}"
if [[ "$project_dir" != "/opt/cloudward" || "$backup_dir" != "/var/backups/cloudward/postgres" ]]; then
  printf 'Only the documented production project and backup directories are accepted.\n' >&2
  exit 64
fi

umask 077
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$backup_dir/cloudward-$timestamp.dump"
temporary="$destination.partial"
install -d -m 0700 "$backup_dir"

cd "$project_dir"
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml \
  exec -T postgres pg_dump --username cloudward --dbname cloudward --format=custom >"$temporary"
test -s "$temporary"
mv "$temporary" "$destination"
printf '%s\n' "$destination"
