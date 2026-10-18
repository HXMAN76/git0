#!/bin/bash
# Run pytest on the EC2 host against the production FalkorDB (no published port, so tests run in a throwaway
# container on the compose network). Tests only create and delete their own test_* graphs.
# Usage: AWS_PROFILE=rag deploy/aws/remote-test.sh [pytest args...]   (default: tests)
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
REGION=${REGION:-ap-south-1}
BUCKET=${BUCKET:-membranch-ship-587806480009}
INSTANCE=${INSTANCE:-i-054a7724ad97534db}
TMPD=$(mktemp -d)
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
ARGS="${*:-tests}"

tar czf "$TMPD/t.tgz" pyproject.toml uv.lock .python-version README.md src cypher demo_project tests
aws s3 cp "$(win "$TMPD/t.tgz")" "s3://$BUCKET/t.tgz" --region "$REGION" >/dev/null
URL=$(aws s3 presign "s3://$BUCKET/t.tgz" --region "$REGION" --expires-in 900)

URL="$URL" ARGS="$ARGS" python - > "$TMPD/p.json" <<'PY'
import json, os
url, args = os.environ["URL"], os.environ["ARGS"]
print(json.dumps({"executionTimeout": ["900"], "commands": [
    "set -uo pipefail",
    "rm -rf /opt/membranch/test && mkdir -p /opt/membranch/test && cd /opt/membranch/test",
    f'curl -fsS "{url}" | tar xz',
    "PW=$(grep '^FALKORDB_PASSWORD=' /opt/membranch/.env | cut -d= -f2-)",
    "docker run --rm --network membranch_default -v /opt/membranch/test:/w -v /opt/membranch/uvcache:/root/.cache/uv"
    ' -w /w -e FALKORDB_URL="redis://:$PW@falkordb:6379" ghcr.io/astral-sh/uv:python3.12-bookworm-slim'
    f" sh -c 'apt-get update -qq >/dev/null && apt-get install -y -qq git >/dev/null && uv sync -q --frozen && uv run pytest -q -x {args} 2>&1 | tail -60'",
]}))
PY

CMD=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
  --parameters "file://$(win "$TMPD/p.json")" --query Command.CommandId --output text)
for _ in $(seq 1 120); do
  S=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$S" in Success|Failed|Cancelled|TimedOut) break ;; esac
  sleep 5
done
aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
aws s3 rm "s3://$BUCKET/t.tgz" --region "$REGION" >/dev/null
