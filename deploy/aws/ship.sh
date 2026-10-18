#!/bin/bash
# Dev-loop deploy without CI: build web/dist locally, upload a source tarball to a private S3 bucket, and have
# the EC2 host fetch it through a 15-minute presigned URL, build the image there and restart only the api.
# The repo is private and the host has no GitHub credentials, hence the presigned URL.
# Usage: AWS_PROFILE=rag deploy/aws/ship.sh [--skip-web]
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
REGION=${REGION:-ap-south-1}
BUCKET=${BUCKET:-membranch-ship-587806480009}
INSTANCE=${INSTANCE:-i-054a7724ad97534db}
TAG="dev-$(date +%s)"
TMPD=$(mktemp -d)
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }

[[ "${1:-}" == "--skip-web" ]] || (cd web && pnpm build)
tar czf "$TMPD/src.tgz" pyproject.toml uv.lock .python-version README.md src cypher demo_project web/dist \
  deploy/aws/Dockerfile.prebuilt
aws s3 cp "$(win "$TMPD/src.tgz")" "s3://$BUCKET/src.tgz" --region "$REGION" >/dev/null
URL=$(aws s3 presign "s3://$BUCKET/src.tgz" --region "$REGION" --expires-in 900)

URL="$URL" TAG="$TAG" python - > "$TMPD/ship-params.json" <<'PY'
import json, os
url, tag = os.environ["URL"], os.environ["TAG"]
print(json.dumps({"executionTimeout": ["900"], "commands": [
    "set -euo pipefail",
    "rm -rf /opt/membranch/build && mkdir -p /opt/membranch/build && cd /opt/membranch/build",
    f'curl -fsS "{url}" | tar xz',
    f"docker build -q -f deploy/aws/Dockerfile.prebuilt -t membranch-api:{tag} .",
    f'cd /opt/membranch && sed -i "s|^IMAGE=.*|IMAGE=membranch-api:{tag}|" .env',
    "docker compose --env-file .env up -d --no-deps api",
    "docker image prune -f >/dev/null",
    "for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8080/api/health && exit 0; sleep 2; done; "
    "docker compose logs --tail 60 api; exit 1",
]}))
PY

CMD=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
  --comment "ship $TAG" --parameters "file://$(win "$TMPD/ship-params.json")" --query Command.CommandId --output text)
echo "ssm command $CMD ($TAG)"
for _ in $(seq 1 120); do
  S=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$S" in Success|Failed|Cancelled|TimedOut) break ;; esac
  sleep 5
done
aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | tail -40
aws s3 rm "s3://$BUCKET/src.tgz" --region "$REGION" >/dev/null
[[ "$S" == "Success" ]]
