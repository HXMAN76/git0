#!/bin/bash
# GCE startup script for the FalkorDB VM (runs on every boot, idempotent).
# Data lives on the separate persistent disk "falkordb-data" (auto-delete=no) mounted at /var/lib/falkordb.
# /var/lib/falkordb/data is the image's Redis `dir` (verified with CONFIG GET dir on v4.22.1).
set -euo pipefail
DEV=/dev/disk/by-id/google-falkordb-data
MNT=/var/lib/falkordb
mkdir -p "$MNT"
blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -F "$DEV"
grep -q "$DEV" /etc/fstab || echo "$DEV $MNT ext4 defaults,nofail 0 2" >> /etc/fstab
mount -a
mkdir -p "$MNT/data"
command -v docker >/dev/null || (curl -fsSL https://get.docker.com | sh)
meta() { curl -fsS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
PW=$(meta falkordb-password)
docker rm -f falkordb 2>/dev/null || true
docker run -d --name falkordb --restart=always -p 6379:6379 \
  -e REDIS_ARGS="--requirepass ${PW} --appendonly yes" \
  -e FALKORDB_ARGS="MAX_QUEUED_QUERIES 100 TIMEOUT 5000 RESULTSET_SIZE 10000" \
  -v "$MNT/data:/var/lib/falkordb/data" \
  falkordb/falkordb:v4.22.1
