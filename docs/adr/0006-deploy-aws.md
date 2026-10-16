# ADR 0006: Deploy on AWS (one EC2 host, Caddy HTTPS on sslip.io)

**Status:** accepted 2026-10-16 · supersedes [ADR 0005](0005-deploy-gcp.md) · **Owner:** Person D (+ the teammate whose AWS account we use)

## Context
A teammate's friend offers an AWS account, so we use it instead of GCP. Research: [docs/research/07-aws-deploy.md](../research/07-aws-deploy.md). Facts that drove the choice:
- App Runner is closed to new customers. Lightsail containers have no private networking and no volumes. ECS Express Mode needs an ALB (~$95+/month) and still can't host FalkorDB.
- 2025+ Free-plan accounts: `t3.small` is free-tier eligible, `t3.medium` isn't (a Free-plan account blocks non-eligible usage).
- CloudFront gives a free `*.cloudfront.net` HTTPS URL (always-free 1 TB / 10M requests) and passes SSE through when caching is off.

## Decision
- **One EC2 instance** (`t3.small` default, `t3.medium` if the account is on the Paid plan), Amazon Linux 2023, Elastic IP, IMDSv2 only. Docker compose runs `falkordb/falkordb:v4.22.1` (password, AOF, **no published port**) and the api image on `:80`. Files: `deploy/aws/compose.prod.yaml`, `host-deploy.sh`, `user-data.tpl.sh`.
- **HTTPS: Caddy on the host** (`deploy/aws/Caddyfile`) at `https://<elastic-ip-dashed>.sslip.io`, with automatic certificates (Let's Encrypt, ZeroSSL fallback via the ACME email) and `flush_interval -1` so SSE is never buffered. The security group opens only 80/443. No SSH: shell access via SSM Session Manager.
- **Update 2026-10-16:** the first `infra` run hit `AccessDenied ... Your account must be verified before you can add new CloudFront resources`. CloudFront is now opt-in (`USE_CLOUDFRONT=1`, origin = the Caddy HTTPS host) for after AWS Support verifies the account. sslip.io is **not** on the Public Suffix List, so LE's 50-certs/week limit is shared by all sslip.io users. The ZeroSSL fallback and the persisted `caddy-data` volume (no re-issuance on redeploy) cover that.
- **Secrets:** SSM Parameter Store SecureStrings `/membranch/falkordb-password|groq-api-key|gemini-api-key`, read on the host at deploy time into a `0600` `.env`.
- **CD:** `.github/workflows/deploy-aws.yml` runs after `ci` succeeds on `main`. GitHub OIDC → IAM role `membranch-gha-deploy` (trust: `refs/heads/main` of this repo only; the repo uses GitHub's **immutable subject** `repo:HXMAN76@118720278/git0@1421957470:ref:...`, which `setup.sh oidc` reads from the GitHub API, plus the legacy `repo:HXMAN76/git0:...` form), then ECR push, then `ssm send-command` ships `compose.yaml` + `Caddyfile` + `host-deploy.sh` and runs it on the host, then a health smoke test through CloudFront. No long-lived AWS keys anywhere.
- **Budget** with email alerts (default $30/month).

## Consequences
- ~$38/month on Paid-plan pricing (≈$10 for the judging week). On the Free plan with credits, `t3.small` is covered.
- **SSE heartbeat:** keep the `: ping` comment every 15 s (Person B/D). Caddy doesn't need it, but CloudFront would (60 s max gap between bytes), and so do most corporate proxies.
- Single host, no replica. Deploys restart the api container (a few seconds of downtime). FalkorDB keeps running across deploys. Acceptable for a demo.
- `deploy/gcp/` (ADR 0005) and Railway (ADR 0004) remain as fallbacks with the same Dockerfile.

## Status
- 2026-10-16: live at https://15-252-11-70.sslip.io (Let's Encrypt cert, t3.small, ap-south-1). The first deploy failed `AssumeRoleWithWebIdentity` because of the immutable OIDC subject. Fixed by `setup.sh oidc`.
