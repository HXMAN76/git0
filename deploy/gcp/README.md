# Deploy on GCP (runbook)

Design and reasons: [ADR 0005](../../docs/adr/0005-deploy-gcp.md). Research: [06-gcp-deploy.md](../../docs/research/06-gcp-deploy.md).

```
Internet ──HTTPS──► Cloud Run membranch-api (min 1, asia-south1)  ──Direct VPC egress──►  VM falkordb 10.20.0.10:6379
                          ▲  secrets: FALKORDB_URL, GROQ_API_KEY, GEMINI_API_KEY              (password, AOF, data disk)
GitHub main ─ci ok─► deploy.yml ─OIDC/WIF─► build ► Artifact Registry ► new revision
```

## One-time setup (lead, with the account that holds the free-trial credits)
```bash
cp deploy/gcp/membranch.env.example deploy/gcp/membranch.env   # fill ACCOUNT, PROJECT_ID, BILLING_ACCOUNT_ID
deploy/gcp/setup.sh infra          # ~5 min. Idempotent, safe to re-run
deploy/gcp/setup.sh llm-secrets    # paste Groq/Gemini keys (hidden input)
deploy/gcp/setup.sh first-deploy   # Cloud Build + create the service, prints the URL
deploy/gcp/setup.sh github         # sets GCP_* repo variables, which switches on auto-deploy
deploy/gcp/setup.sh budget         # alerts at 50/80/100 % of BUDGET_USD
```
The script uses its own gcloud configuration `membranch` and pins the project. Your default gcloud account/project is left alone.

## After setup
- Every merge to `main` deploys once CI is green (Actions → deploy). Manual: Actions → deploy → Run workflow.
- `deploy/gcp/setup.sh status`: URL, live revision, VM state.
- Rollback: `gcloud run services update-traffic membranch-api --to-revisions=<previous>=100 --region asia-south1`.
- FalkorDB shell: `gcloud compute ssh falkordb --tunnel-through-iap --zone asia-south1-a`, then `sudo docker exec -it falkordb redis-cli -a "$PW"`.
- Change an LLM key: `deploy/gcp/setup.sh llm-secrets`, then redeploy (the service reads `:latest` at revision start).

## Checks for Person D in Phase 0
- [ ] `curl -fsS <url>/api/health` returns `{"ok":true,...}` (proves Direct VPC egress + firewall + password)
- [ ] `curl -N <url>/api/...stream...` shows SSE events arriving one by one, not in one lump
- [ ] Push a trivial commit to `main` and watch `deploy` go green

## After judging
`gcloud projects delete $PROJECT_ID` (or `gcloud run services update membranch-api --min-instances=0` + stop the VM) so the credit isn't drained.
