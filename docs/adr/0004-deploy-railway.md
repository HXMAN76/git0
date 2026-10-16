# ADR 0004: Deploy on Railway (api + private FalkorDB)

**Status:** superseded by [ADR 0005](0005-deploy-gcp.md) (team has GCP credits) · **Owner:** Person D

## Context
We need a live URL that stays up during judging. FalkorDB Cloud free tier stops after 1 idle day, has no TLS and deletes after 7 days. Render free sleeps after 15 minutes (~1 minute cold start).

## Decision
Railway Hobby project: service `falkordb` from the official FalkorDB template (volume, private network only) and service `api` from the repo Dockerfile (public domain), `FALKORDB_URL=${{falkordb.FALKORDB_PRIVATE_URL}}` (check the variable name in the template). Auto-deploy on push to `main`. Set `FALKORDB_ARGS` TIMEOUT 5000.

## Consequences
~$5-10 total. Fly.io is the backup (docs/research/04-deploy-ci.md). Deploy the hello-world on day 1 (Phase 0), not at the end.
