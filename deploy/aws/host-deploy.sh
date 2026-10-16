#!/bin/bash
# Runs ON the EC2 host (via SSM Run Command from GitHub Actions, or by hand): deploy-host <image-uri>
# Pulls secrets from SSM Parameter Store, writes /opt/membranch/.env, then (re)starts the compose stack.
set -euo pipefail
IMAGE="${1:?usage: $0 <image-uri>}"
cd /opt/membranch
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
REGION=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
param() { aws ssm get-parameter --region "$REGION" --with-decryption --name "/membranch/$1" \
            --query Parameter.Value --output text 2>/dev/null || true; }
umask 077
{
  echo "IMAGE=$IMAGE"
  echo "FALKORDB_PASSWORD=$(param falkordb-password)"
  for k in groq-api-key gemini-api-key; do   # only set keys that exist; empty values would mask errors
    v=$(param "$k"); if [[ -n "$v" ]]; then echo "$(echo "$k" | tr a-z- A-Z_)=$v"; fi
  done
  echo 'CORS_ORIGINS=[]'
} > .env
[[ -n "$(grep '^FALKORDB_PASSWORD=.\+' .env)" ]] || { echo "missing /membranch/falkordb-password"; exit 1; }
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${IMAGE%%/*}"
docker compose --env-file .env pull api
docker compose --env-file .env up -d --remove-orphans
docker image prune -f >/dev/null
for i in $(seq 1 30); do
  curl -fsS http://localhost/api/health && { echo; echo "deployed $IMAGE"; exit 0; }
  sleep 2
done
echo "health check failed"; docker compose logs --tail 50 api; exit 1
