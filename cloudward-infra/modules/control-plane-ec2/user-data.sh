#!/usr/bin/env bash
set -euo pipefail

dnf install -y docker git jq
systemctl enable --now docker

install -d -m 0750 -o root -g root /opt/cloudward
install -d -m 0750 -o root -g root /etc/cloudward

tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "local",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  }
}
JSON

systemctl restart docker

cat >/etc/cloudward/DEPLOYMENT_REQUIRED <<'EOF'
Terraform intentionally prepares only the AL2023 host.
Deploy the reviewed CloudWard Docker Compose release and secrets through SSM or
an approved delivery workflow. Do not place secrets in Terraform or user data.
EOF
