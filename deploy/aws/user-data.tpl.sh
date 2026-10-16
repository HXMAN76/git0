#!/bin/bash
# EC2 user-data (Amazon Linux 2023). setup.sh fills in __COMPOSE_B64__ / __DEPLOY_B64__.
# AL2023 ships the SSM agent and AWS CLI v2; we add Docker + the compose plugin.
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
mkdir -p /usr/libexec/docker/cli-plugins
curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64
chmod +x /usr/libexec/docker/cli-plugins/docker-compose
docker compose version
mkdir -p /opt/membranch /var/lib/membranch/falkordb
echo "__COMPOSE_B64__" | base64 -d > /opt/membranch/compose.yaml
echo "__DEPLOY_B64__" | base64 -d > /opt/membranch/host-deploy.sh
chmod +x /opt/membranch/host-deploy.sh
ln -sf /opt/membranch/host-deploy.sh /usr/local/bin/membranch-deploy
