# Deploy on AWS (runbook)

Design and reasons: [ADR 0006](../../docs/adr/0006-deploy-aws.md). Research: [07-aws-deploy.md](../../docs/research/07-aws-deploy.md).

```
judge ──HTTPS──► EC2 t3.small, ap-south-1 (Elastic IP, SG: 80/443 only)
                 ├─ caddy     :443 https://<ip-dashed>.sslip.io (auto TLS), :80 → redirect + ACME
                 ├─ api       127.0.0.1:8080
                 └─ falkordb  (no published port, password, AOF)
GitHub main ─ci ok─► deploy-aws.yml ─OIDC─► ECR push ─► SSM Run Command: ship compose/Caddyfile/host-deploy.sh, run it ─► HTTPS health check
```

## One-time setup (whoever has credentials for the AWS account)
```bash
aws configure --profile membranch          # access key of an admin IAM user in the friend's account (or `aws configure sso`)
cp deploy/aws/membranch.env.example deploy/aws/membranch.env   # set ALERT_EMAIL (required: budget + TLS cert account)
deploy/aws/setup.sh infra        # asks you to confirm the account id. ~5 min, safe to re-run
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
- [ ] `deploy/aws/setup.sh status` shows `/api/health` ok over HTTPS (a valid certificate, no `-k`)
- [ ] SSE: `curl -N $PUBLIC_URL/api/...` streams events one by one (15 s `: ping` heartbeat)
- [ ] Cert issuer: `echo | openssl s_client -connect <site>:443 2>/dev/null | openssl x509 -noout -issuer` (LE or ZeroSSL)
- [ ] A merge to `main` triggers `deploy-aws` and it goes green

## CloudFront later (optional)
Once AWS Support has verified the account (the console asks for it on CloudFront), set `USE_CLOUDFRONT=1` in `membranch.env` and re-run `infra`. It adds a `*.cloudfront.net` URL in front of the Caddy host.

## After judging
`deploy/aws/setup.sh teardown` prints the delete commands (CloudFront, EC2, EIP, SG, ECR, params, roles). Run them so the friend's account isn't billed.
