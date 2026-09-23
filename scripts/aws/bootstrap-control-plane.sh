#!/usr/bin/env bash
set -euo pipefail

if [[ "${CLOUDWARD_BOOTSTRAP_CONFIRM:-}" != "BOOTSTRAP_CONTROL_PLANE" ]]; then
  printf 'Refusing to modify this host. Set CLOUDWARD_BOOTSTRAP_CONFIRM=BOOTSTRAP_CONTROL_PLANE after reviewing the script.\n' >&2
  exit 64
fi
if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run as root on the intended CloudWard EC2 host.\n' >&2
  exit 77
fi

project_dir="${CLOUDWARD_PROJECT_DIR:-/opt/cloudward}"
if [[ "$project_dir" != "/opt/cloudward" || ! -f "$project_dir/docker-compose.production.yml" ]]; then
  printf 'Expected a reviewed checkout at /opt/cloudward.\n' >&2
  exit 66
fi
if [[ ! -f "$project_dir/.env.production" ]]; then
  printf 'Create root-owned /opt/cloudward/.env.production before bootstrap.\n' >&2
  exit 66
fi
if ! command -v docker >/dev/null 2>&1 || ! command -v aws >/dev/null 2>&1 || ! command -v kubectl >/dev/null 2>&1; then
  printf 'Docker Compose, AWS CLI v2, and kubectl must be installed through the approved host build process first.\n' >&2
  exit 69
fi

if ! getent group cloudward >/dev/null 2>&1; then
  groupadd --system --gid 10001 cloudward
fi
if ! id cloudward >/dev/null 2>&1; then
  useradd --system --uid 10001 --gid cloudward --home-dir /opt/cloudward --shell /usr/sbin/nologin cloudward
fi

install -d -m 0700 /var/backups/cloudward/postgres
install -d -m 0750 -o cloudward -g cloudward "$project_dir/.aws"
chown root:root "$project_dir/.env.production"
chmod 0600 "$project_dir/.env.production"

aws eks update-kubeconfig \
  --region eu-north-1 \
  --name cloudward-aws-eu-north-1 \
  --alias cloudward-eks \
  --kubeconfig "$project_dir/.aws/cloudward-kubeconfig"
chown cloudward:cloudward "$project_dir/.aws/cloudward-kubeconfig"
chmod 0400 "$project_dir/.aws/cloudward-kubeconfig"

install -m 0644 "$project_dir/scripts/aws/cloudward-compose.service" /etc/systemd/system/cloudward-compose.service
install -m 0644 "$project_dir/scripts/aws/cloudward-telemetry-bridge.service" /etc/systemd/system/cloudward-telemetry-bridge.service
systemctl daemon-reload
systemctl enable cloudward-compose.service
systemctl enable cloudward-telemetry-bridge.service

printf 'Host and cloudward-eks context prepared. Nothing was started. Review configuration, then start the Compose and telemetry services explicitly.\n'
