# ADR 0005: Deploy on Google Cloud (Cloud Run + private FalkorDB VM)

**Status:** superseded by [ADR 0006](0006-deploy-aws.md) (team switched to an AWS account) · fallback · **Owner:** Person D

## Context
The team has a GCP free trial ($300 credit, 90 days, card required). We need a live HTTPS URL that stays warm through judging, auto-deploys from `main`, and keeps FalkorDB off the public internet. Research: [docs/research/06-gcp-deploy.md](../research/06-gcp-deploy.md).

## Decision
- **API:** Cloud Run service `membranch-api` in `asia-south1`, from the repo Dockerfile. `min-instances=1`, `--no-cpu-throttling` (no cold starts, background work allowed), `max-instances=2`, `timeout=3600` (SSE), `concurrency=40`. Managed `*.run.app` HTTPS URL.
- **FalkorDB:** Debian 12 `e2-medium` VM `falkordb` at internal IP `10.20.0.10`, `falkordb/falkordb:v4.22.1` with a password and AOF, data on a separate `pd-balanced` disk (`auto-delete=no`). Reached via **Direct VPC egress** (`--vpc-egress=private-ranges-only`, no connector). The firewall allows 6379 only from `10.20.0.0/24`, and SSH only via IAP.
- **Secrets:** `FALKORDB_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY` in Secret Manager, mounted as env vars. Nothing secret lives in GitHub.
- **CD:** `.github/workflows/deploy.yml` runs after `ci` succeeds on `main`. GitHub OIDC → Workload Identity Federation (only `HXMAN76/git0` @ `refs/heads/main`) → `gha-deployer` SA (run.admin, artifactregistry.writer, actAs `api-runtime`). It builds, pushes to Artifact Registry and swaps the image. Runtime config lives on the service, set once by `deploy/gcp/setup.sh`.
- **Isolation from other GCP work:** `setup.sh` runs under its own gcloud configuration `membranch` with the project pinned (`CLOUDSDK_ACTIVE_CONFIG_NAME`, `CLOUDSDK_CORE_PROJECT`), so a different default project/account is never touched.
- **Budget alert** at 50/80/100 % of $150.

## Consequences
- Estimated ~$80-130/month while running, so ~$20-30 for the hackathon week. Well inside the credit. **Delete the project after judging** (or scale `min-instances=0` and stop the VM).
- Unverified until first deploy: SSE streams arrive incrementally through Cloud Run (`curl -N`), and Direct VPC egress works in `asia-south1`. Person D checks both in Phase 0.
- FalkorDB is a single VM with no replica. Acceptable for a demo. The data disk survives VM recreation, and `GRAPH.COPY`/tenant TTL keep the data small.
- Fallback if GCP blocks us: Railway (ADR 0004) still works with the same Dockerfile.
