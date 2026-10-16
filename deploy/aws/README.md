# Deploy on AWS (runbook)

Design and reasons: [ADR 0006](../../docs/adr/0006-deploy-aws.md). Research: [07-aws-deploy.md](../../docs/research/07-aws-deploy.md).

```
judge ──HTTPS──► CloudFront (*.cloudfront.net, no cache) ──HTTP :80 (SG: CloudFront IPs only)──► EC2 t3.small, ap-south-1
                                                                                                  ├─ api        :80 → 8080
                                                                                                  └─ falkordb   (no published port, password, AOF)
GitHub main ─ci ok─► deploy-aws.yml ─OIDC─► ECR push ─► SSM Run Command: membranch-deploy <image> ─► health check
```

## One-time setup (whoever has credentials for the AWS account)
```bash
aws configure --profile membranch          # access key of an admin IAM user in the friend's account (or `aws configure sso`)
cp deploy/aws/membranch.env.example deploy/aws/membranch.env   # set ALERT_EMAIL, INSTANCE_TYPE
deploy/aws/setup.sh infra        # asks you to confirm the account id. ~5 min + ~5-10 min for CloudFront
deploy/aws/setup.sh llm-secrets  # Groq/Gemini keys → SSM SecureString (hidden input)
deploy/aws/setup.sh github       # sets AWS_* repo variables and triggers the first deploy
deploy/aws/setup.sh budget       # cost alerts by email (confirm the subscription email)
deploy/aws/setup.sh status       # URL, instance, SSM agent, CloudFront, /api/health
```
Resource ids land in `deploy/aws/membranch.state` (gitignored), so re-running `infra` is safe. **Don't commit that file or `membranch.env`.**

## Day-to-day
- Merge to `main` → CI green → `deploy-aws` rolls out automatically. Manual: Actions → deploy-aws → Run workflow.
- Shell on the host: `aws ssm start-session --target <INSTANCE_ID> --profile membranch`, then `cd /opt/membranch && sudo docker compose logs -f api`.
- Roll back: Actions → deploy-aws → re-run an older successful run (it redeploys that commit's image).
- Rotate an LLM key: `deploy/aws/setup.sh llm-secrets`, then re-run the deploy.

## Phase 0 checks (Person D)
- [ ] `deploy/aws/setup.sh status` shows `/api/health` ok through CloudFront
- [ ] SSE: `curl -N $PUBLIC_URL/api/...` streams events one by one; idle streams survive > 60 s (needs the 15 s `: ping` heartbeat)
- [ ] A merge to `main` triggers `deploy-aws` and it goes green

## After judging
`deploy/aws/setup.sh teardown` prints the delete commands (CloudFront, EC2, EIP, SG, ECR, params, roles). Run them so the friend's account isn't billed.
