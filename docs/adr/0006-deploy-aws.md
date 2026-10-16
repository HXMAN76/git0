# ADR 0006: Deploy on AWS (one EC2 host behind CloudFront)

**Status:** accepted 2026-10-16 · supersedes [ADR 0005](0005-deploy-gcp.md) · **Owner:** Person D (+ the teammate whose AWS account we use)

## Context
A teammate's friend offers an AWS account, so we use it instead of GCP. Research: [docs/research/07-aws-deploy.md](../research/07-aws-deploy.md). Facts that drove the choice:
- App Runner is closed to new customers. Lightsail containers have no private networking and no volumes. ECS Express Mode needs an ALB (~$95+/month) and still can't host FalkorDB.
- 2025+ Free-plan accounts: `t3.small` is free-tier eligible, `t3.medium` isn't (a Free-plan account blocks non-eligible usage).
- CloudFront gives a free `*.cloudfront.net` HTTPS URL (always-free 1 TB / 10M requests) and passes SSE through when caching is off.

## Decision
- **One EC2 instance** (`t3.small` default, `t3.medium` if the account is on the Paid plan), Amazon Linux 2023, Elastic IP, IMDSv2 only. Docker compose runs `falkordb/falkordb:v4.22.1` (password, AOF, **no published port**) and the api image on `:80`. Files: `deploy/aws/compose.prod.yaml`, `host-deploy.sh`, `user-data.tpl.sh`.
- **CloudFront** in front: `CachingDisabled` + `AllViewerExceptHostHeader`, HTTP-only origin, origin read timeout 60 s, compression off (don't buffer SSE). The security group allows `:80` **only** from the CloudFront origin-facing prefix list. No SSH: shell access via SSM Session Manager.
- **Secrets:** SSM Parameter Store SecureStrings `/membranch/falkordb-password|groq-api-key|gemini-api-key`, read on the host at deploy time into a `0600` `.env`.
- **CD:** `.github/workflows/deploy-aws.yml` runs after `ci` succeeds on `main`. GitHub OIDC → IAM role `membranch-gha-deploy` (trust: `repo:HXMAN76/git0:ref:refs/heads/main`), then ECR push, then `ssm send-command` runs `membranch-deploy <image>` on the host, then a health smoke test through CloudFront. No long-lived AWS keys anywhere.
- **Budget** with email alerts (default $30/month).

## Consequences
- ~$38/month on Paid-plan pricing (≈$10 for the judging week). On the Free plan with credits, `t3.small` is covered.
- **SSE through CloudFront:** the origin read timeout (60 s) is also the max gap between bytes. Our SSE endpoints **must send a heartbeat comment (`: ping`) every 15 s** (Person D/B). Verify with `curl -N` on day 1.
- Single host, no replica. Deploys restart the api container (a few seconds of downtime). FalkorDB keeps running across deploys. Acceptable for a demo.
- `deploy/gcp/` (ADR 0005) and Railway (ADR 0004) remain as fallbacks with the same Dockerfile.
