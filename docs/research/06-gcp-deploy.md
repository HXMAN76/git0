# 06 - Deploying the hackathon app on Google Cloud (free trial credits)

Research date: 2026-10-16. Region: asia-south1 (Mumbai). Team: India, 4 people, 3-day hackathon, judging window about 1 week.
Stack: FastAPI (Python 3.12) container that also serves a built React SPA, SSE streaming, FalkorDB `falkordb/falkordb:v4.22.1` (port 6379, data dir per user brief `/var/lib/falkordb/data`, about 1-2 GB RAM).

Legend for every factual claim:
- [V] read from an official Google/vendor page or API in this session
- [S] search-result snippet only, not opened in full
- [U] unverified: third-party mirror, recalled from memory, or pricing that could not be read. Check before relying on it.
- [I] my inference from the sources above

No gcloud command that creates, modifies or deletes a resource was run. `gcloud ... --help` was read locally to confirm flag names.

---

## 0. Bottom line

- **Recommend Option B**: Cloud Run for the API (min-instances=1, no CPU throttling, 60 min timeout) plus one e2-medium Compute Engine VM for FalkorDB, joined by Direct VPC egress on a private subnet. It gives a managed HTTPS `*.run.app` URL with no domain and no cert setup, and it auto-deploys from GitHub Actions. Estimated cost about $80-130/month, or about $20-30 for the judging week [U].
- **Option A is cheaper** (about $37-41/month, about $9 for the week) [U], but it needs sslip.io plus Caddy plus Let's Encrypt, which adds a moving part on judging day. CI deploys would need SSH.
- **Free tier does not cover this.** The always-free e2-micro is not offered in asia-south1 and has 1 GB RAM, which is too small for FalkorDB. Everything here is paid, which the $300 trial credit covers.
- **Do not use `gcloud compute instances create-with-container`.** Its startup agent stopped working for new VMs on 2026-07-31 [V].

---

## 1. Free trial and always-free tier

**Free Trial** [V] (https://docs.cloud.google.com/free/docs/free-trial):
- $300 USD Welcome credit, valid 90 days from signup.
- A billing account and a valid credit card or other payment method are required. The verification charge is a temporary hold, not a real charge.
- Restrictions: no GPUs on VMs; no quota increase requests during the trial; no Google Cloud Marketplace; no Windows Server VMs; no VMware Engine. The credit cannot pay for Gemini API in AI Studio or for generative AI partner models offered as managed APIs. Crypto mining is prohibited.
- The page gives no maximum vCPU count. The default regional CPU quota for asia-south1 on a new project is unverified [U]. A 2-vCPU e2-medium plus a 1-vCPU Cloud Run service should fit.
- When the credit runs out or 90 days pass without an upgrade, billing is disabled and resources stop. Trial resources are deleted if you do not upgrade within the 30-day grace period. Upgrading to a paid billing account can recover them [V].
- Search snippets say the same thing about the card requirement and the 90-day window [S] (https://docs.cloud.google.com/free?authuser=0).
- Whether Indian-issued cards and Indian billing addresses are accepted for the trial is unverified [U]. Check at signup.

**Always-free tier** [V] (https://docs.cloud.google.com/free/docs/free-cloud-features):
- Compute Engine e2-micro: one non-preemptible VM per month in us-west1, us-central1 or us-east1 only. Not asia-south1. 1 GB RAM, too small for FalkorDB.
- Compute Engine egress: 1 GB/month outbound from North America.
- Cloud Run (request-based billing): 2,000,000 requests, 360,000 GB-seconds memory, 180,000 vCPU-seconds, 1 GB outbound from North America per month.
- Artifact Registry: 0.5 GB storage per month.
- Cloud Build: 2,500 build-minutes per month on e2-standard-2.
- Limits are per billing account, do not roll over, and require an active trial or paid billing account. Google can change the tier with 30 days' notice.
- Free-tier Cloud Run instance-based limits (240,000 vCPU-s, 450,000 GiB-s, "based on us-central1 pricing") appear in a search snippet only [S, U].

**Implication:** a min-instances=1 Cloud Run service runs about 2.59M vCPU-seconds per month, far above the 180k request-based free quota. Expect to pay for the API. Budget the week, not the month.

---

## 2. Option A - one VM, docker compose, Caddy

Layout: one e2-medium (2 vCPU, 4 GB) in asia-south1-a runs `falkordb`, `api` and `caddy` under docker compose. Only ports 80 and 443 are open to the internet. 6379 stays on the compose network and is not published.

### 2.1 HTTPS without a domain

- Caddy does not get public certificates for bare IP addresses. It serves IPs with self-signed certs [V] (https://caddyserver.com/docs/automatic-https).
- Public DNS names get certs from an ACME CA such as Let's Encrypt [V]. A hostname qualifies only if it is not an IP literal [V].
- `34-93-1-2.sslip.io` style names resolve to the embedded IP. Caddy then issues a normal Let's Encrypt cert for that hostname, provided DNS resolves and ports 80/443 are reachable [I, based on the Caddy rules above]. Recommended hostname format: replace dots with dashes in the reserved static IP, e.g. `<ip-with-dashes>.sslip.io`.
- Risk: Let's Encrypt limits issuance to 50 certificates per registered domain (or IPv4 address) every 7 days, and the count is shared across accounts [V] (https://letsencrypt.org/docs/rate-limits/ , snippet [S]). If sslip.io is treated as one registered domain, its shared bucket could be exhausted by other users. Whether sslip.io or nip.io is on the Public Suffix List, which decides this, is unverified [U]. Mitigation: have a fallback hostname ready, or use your own domain.
- Let's Encrypt has issued IP-address certificates generally since 2026-01-15, but only with the 160-hour `shortlived` profile [V] (https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html). Caddy support for that profile is unverified [U]. Do not rely on it for judging day.

### 2.2 Container-Optimized OS vs Debian

- Container-Optimized OS: newer versions no longer support konlet, so you can no longer use `gce-container-declaration` metadata to start a container [V] (https://docs.cloud.google.com/compute/docs/containers/prepare-for-container-agent-shutdown). COS also has a read-only root and no `apt`, and docker compose is not included [I].
- **Debian 12 + Docker** is the simpler choice for compose and certs [I]. Install Docker via the official `get.docker.com` script, which includes the compose plugin [U, widely used but not fetched].

### 2.3 Static IP cost

- Reserve a regional static external IPv4 and attach it to the VM [I].
- Public IPv4 addresses are billed hourly whether in use or not. Recalled rates are about $0.005/h in use and $0.01/h reserved and idle, roughly $3.65-7.30/month [U, from memory]. The official pricing page could not be read in full.

### 2.4 Cost (asia-south1) [U]

Prices come from a third-party mirror of the Google price list (gcloud-compute.com, asia-south1 page), which I could not check against the official table:
- e2-medium on-demand: $0.0402/h, about $29.38/month. e2-small: $0.0201/h, about $14.69/month.
- pd-balanced: $0.12/GB-month. pd-standard: $0.048/GB-month.

| Item | Monthly |
|---|---|
| e2-medium VM | ~$29.4 |
| 30 GB pd-balanced boot | ~$3.6 |
| Reserved static IPv4 | ~$3.7-7.3 |
| Egress (small) | ~$0-1 |
| **Total** | **~$37-41 (about $9 for the week)** |

### 2.5 Steps for Option A

Use the same `gcloud config` setup as in section 7.

```bash
gcloud compute addresses create membranch-ip --region=REGION
gcloud compute firewall-rules create membranch-web --network=default --allow=tcp:80,tcp:443 --target-tags=web
gcloud compute instances create membranch-vm --zone=ZONE --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB \
  --address=membranch-ip --tags=web --metadata-from-file=startup-script=startup.sh
```

`startup.sh` installs Docker, clones the repo and runs `docker compose up -d --build`, with `restart: always` on each service. The `default` network has `default-allow-*` rules, and `firewall-rules create` above is only needed if those are missing [U]. Check with `gcloud compute firewall-rules list`.

Caddyfile (`SITE_ADDRESS=<ip-with-dashes>.sslip.io`):
```
{$SITE_ADDRESS} {
  reverse_proxy api:8000
}
```
Caddy's `reverse_proxy` flushes `text/event-stream` responses without buffering [U, recalled; verify with a curl test]. Test with `curl -N https://<host>/api/stream`.

Do not publish `6379` to the host. Use compose networks only.

CI deploys are harder here. Either SSH with a deploy key stored in GitHub secrets, or Workload Identity Federation plus IAP tunnel [I].

---

## 3. Option B - Cloud Run API + FalkorDB VM over Direct VPC egress

### 3.1 Cloud Run behaviour that matters

- Request timeout: default 300 s, can be raised to 3600 s (60 min) [V] (https://docs.cloud.google.com/run/docs/configuring/request-timeout). The docs advise retries and reconnect-tolerant handlers for timeouts above 15 min, since a reconnect may land on another instance [V].
- CPU allocation: default is request-based (CPU only while handling a request). `--no-cpu-throttling` switches to instance-based billing, where CPU is allocated for the full instance lifecycle. Instance-based billing needs at least 512 MiB memory [V] (https://docs.cloud.google.com/run/docs/configuring/cpu-allocation).
- Instance-based billing with `min-instances` gives the warm instance full CPU for background work. The docs do not state that `min-instances` requires this. The inference is [I].
- SSE: no official Cloud Run page on SSE buffering was retrieved. A Google dev-forum thread [S] reports HTTP/2 buffering concerns. Test streaming on the deployed revision before judging day [U].
- Concurrency, port and `$PORT`: the container must listen on `$PORT` (default 8080) [I, standard Cloud Run contract]. Concurrency default is 80 [U, recalled]. The gcloud help says it is "unspecified on new services", so set `--concurrency` explicitly.

### 3.2 Direct VPC egress flags [V]

From https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc and `gcloud run deploy --help`:
- `--network=NETWORK --subnet=SUBNET` (either or both; subnet must be a /26 or larger, RFC1918 or 100.64.0.0/10 or 240.0.0.0/4 ranges).
- `--network-tags=TAG,...` is optional, set per revision.
- `--vpc-egress=all-traffic|private-ranges-only`. `private-ranges-only` sends only RFC1918 traffic through the VPC. This is what you want for `10.x` FalkorDB traffic. Internet traffic goes direct, so the VM does not need Cloud NAT for the API.
- IAM: the default Cloud Run service agent role is `roles/run.serviceAgent`, which is sufficient. `roles/compute.networkUser` is a fallback [V].
- No Serverless VPC Access connector is needed. Google recommends a connector only where a 30+ second cold start is an issue [V].

### 3.3 Firewall

Allow 6379 from the subnet range only, to instances tagged `falkordb` (verified flags in `gcloud compute firewall-rules create --help`):
```bash
--direction=INGRESS --action=allow --rules=tcp:6379 --source-ranges=10.20.0.0/24 --target-tags=falkordb
```
Add IAP SSH on `35.235.240.0/20` for admin access. No public 6379 rule.

### 3.4 Cost (asia-south1) [U]

Cloud Run pricing tables were truncated, so the rates below are from memory and search snippets. Mumbai is outside the Tier 1 list in a snippet [S], so it may be Tier 2 and cost more:
- Instance-based, 1 vCPU, 1 GiB, min=1, 24x7: about 2.59M vCPU-s and 2.59M GiB-s per month. At Tier 1-like rates (about $0.000018/vCPU-s, $0.000002/GiB-s) that is about $45/month after free tier. At higher Tier 2 rates, about $65-90/month [U].

| Item | Monthly |
|---|---|
| Cloud Run API, min=1 | ~$45-90 |
| FalkorDB e2-medium VM | ~$29.4 |
| Boot 20 GB + data 10 GB pd-balanced | ~$3.6 |
| Ephemeral public IPv4 on FalkorDB VM (needed to pull the image) | ~$3.7 |
| **Total** | **~$80-127 (about $20-30 for the week)** |

Note: Cloud NAT would avoid the public IP on the VM but adds a fixed hourly charge. Its price is unverified [U]. Ephemeral IP is simpler for a week.

### 3.5 Steps for Option B

Use the commands in section 7.

---

## 4. FalkorDB on a VM

### 4.1 Replacing `create-with-container`

- `gcloud compute instances create-with-container` is deprecated [V] (gcloud reference page). The container startup agent and `gce-container-declaration` stopped working for new VMs on **2026-07-31**, and support ends **2027-07-31** [V] (https://docs.cloud.google.com/compute/docs/containers/prepare-for-container-agent-shutdown).
- Replacement: a startup script or cloud-init that installs Docker and runs the container [V]. Container-Optimized OS remains supported but without konlet [V].
- Use a plain Debian 12 VM with a startup script. The example in the migrate-containers guide was truncated in my fetch [U]. The `docker run` mapping from `--container-env` to `--env` and `--container-restart-policy` to `--restart` is [V] (same guide).

### 4.2 FalkorDB container facts [V]

From https://docs.falkordb.com/operations/docker.html:
- Ports: 6379 (server), 3000 (browser UI, included only in the `falkordb/falkordb` image).
- Password: pass `REDIS_ARGS="--requirepass <pw>"` as an environment variable.
- Data directory: the docs disagree. Compose examples mount `/data`, the FAQ mounts `/var/lib/falkordb/data`. Confirm by running `docker run --rm --entrypoint sh falkordb/falkordb:v4.22.1 -c 'ls -la /var/lib/falkordb /data'` before relying on it [I].
- Memory: no official recommendation. Your brief says 1-2 GB, which fits e2-medium (4 GB) with headroom.
- Tag `v4.22.1` exists on Docker Hub [V] (`https://hub.docker.com/v2/repositories/falkordb/falkordb/tags/v4.22.1`).

### 4.3 Machine type and disk

- e2-medium (2 vCPU, 4 GB) for FalkorDB with <1 GB data. e2-small (2 GB) is tight once the graph grows, and the brief says 1-2 GB RAM. e2-micro is too small.
- Persistent data disk: separate pd-balanced disk, 10 GB, mounted at `/var/lib/falkordb`, `auto-delete=no` so the data survives VM recreation.

### 4.4 Startup script (for both options; FalkorDB VM in Option B)

```bash
#!/bin/bash
set -euo pipefail
DEV=/dev/disk/by-id/google-falkordb-data
MNT=/var/lib/falkordb
mkdir -p "$MNT"
blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -F "$DEV"
grep -q "$DEV" /etc/fstab || echo "$DEV $MNT ext4 defaults,nofail 0 2" >> /etc/fstab
mount -a
mkdir -p "$MNT/data"
command -v docker >/dev/null || (curl -fsSL https://get.docker.com | sh)
PW=$(curl -fsS -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/falkordb-password)
docker rm -f falkordb 2>/dev/null || true
docker run -d --name falkordb --restart=always -p 6379:6379 \
  -e REDIS_ARGS="--requirepass ${PW}" \
  -v "$MNT/data:/var/lib/falkordb/data" \
  falkordb/falkordb:v4.22.1
```
Password in instance metadata is readable by project viewers. Acceptable for a hackathon; use Secret Manager if you want better hygiene [I]. Data-path line above should match the path confirmed in 4.2.

---

## 5. CI/CD from GitHub Actions to GCP (keyless)

### 5.1 Current action versions [V]

- `google-github-actions/auth@v3` (v3.0.0 published 2025-09-03). README example uses `id-token: write` and `workload_identity_provider`. `service_account` is needed for service-account impersonation. Runs on Node 24, so use a runner that supports it [V] (https://github.com/google-github-actions/auth).
- `google-github-actions/deploy-cloudrun@v3` (v3.0.1 published 2025-09-03). Inputs `service`, `region`, `image`, `source`, `flags`, `env_vars` [V] (https://github.com/google-github-actions/deploy-cloudrun). `flags` is passed through to `gcloud run deploy` unvalidated.
- `google-github-actions/setup-gcloud@v3` (v3.0.1) exists but is not needed for the steps below [V, API tag list].

### 5.2 Required roles for the deployer SA [I + V]

- `roles/run.admin` on the project.
- `roles/iam.serviceAccountUser` on the runtime SA (`api-runtime`), which Cloud Run needs to act as it.
- `roles/artifactregistry.writer` on the Artifact Registry repo.

For `gcloud run deploy --source .` instead of an image, Cloud Build needs extra roles, including `roles/run.builder` on the Compute default SA [S, deploying-source-code page snippet; verify at https://docs.cloud.google.com/run/docs/deploying-source-code]. Image-based CI avoids this.

### 5.3 WIF commands

Flags verified in `gcloud iam workload-identity-pools providers create-oidc --help`. The binding pattern is from third-party guides [S] and must be checked against the official WIF page.

```bash
gcloud iam workload-identity-pools create github-pool --location=global --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github-pool \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='OWNER/REPO' && assertion.ref=='refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding gha-deployer@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/OWNER/REPO"
```
- Without `--attribute-condition`, any GitHub repo could authenticate to the project [S].
- The provider full name for the workflow is `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider`.

### 5.4 Artifact Registry

```bash
gcloud artifacts repositories create membranch --repository-format=docker --location=REGION
```
Flags verified via `--help`. Free tier covers 0.5 GB [V].

### 5.5 Workflow (`.github/workflows/deploy.yml`, sketch)

```yaml
name: deploy
on:
  push:
    branches: [main]
permissions:
  contents: read
  id-token: write
env:
  PROJECT_ID: PROJECT_ID
  REGION: asia-south1
  REPO: membranch
  SERVICE: membranch-api
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4          # use current major
      - uses: google-github-actions/auth@v3
        with:
          workload_identity_provider: projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider
          service_account: gha-deployer@PROJECT_ID.iam.gserviceaccount.com
      - run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev --quiet
      - run: |
          IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${GITHUB_SHA}
          docker build -t "$IMAGE" .
          docker push "$IMAGE"
          echo "IMAGE=$IMAGE" >> "$GITHUB_ENV"
      - id: deploy
        uses: google-github-actions/deploy-cloudrun@v3
        with:
          service: ${{ env.SERVICE }}
          region: ${{ env.REGION }}
          image: ${{ env.IMAGE }}
          env_vars: |
            FALKORDB_HOST=10.20.0.10
            FALKORDB_PORT=6379
          flags: >-
            --service-account=api-runtime@PROJECT_ID.iam.gserviceaccount.com
            --network=membranch-vpc --subnet=run-egress --vpc-egress=private-ranges-only
            --min-instances=1 --max-instances=2 --no-cpu-throttling
            --cpu=1 --memory=1Gi --timeout=3600 --concurrency=40
            --allow-unauthenticated
      - run: echo "${{ steps.deploy.outputs.url }}"
```
- The API must listen on `$PORT`.
- FalkorDB password is not in the sketch. Add it via Secret Manager (`--set-secrets`) or `env_vars`. Not verified here.
- GitHub repo variables: set `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT` if you parameterise the auth step.

### 5.6 Simpler alternative

`gcloud run deploy membranch-api --source . --region REGION ...` builds with Cloud Build and Artifact Registry in one step. It needs the roles in 5.2 and region support for Artifact Registry and Cloud Build [S]. For CI, the image route above is more predictable.

---

## 6. Budget alerts

Flags verified against `gcloud billing budgets create --help` [V]:

```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="membranch-hackathon" \
  --budget-amount=150USD \
  --filter-projects=projects/PROJECT_NUMBER \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.8 \
  --threshold-rule=percent=1.0
```
- `--threshold-rule` is singular and repeatable. The plural `--threshold-rules` in some third-party guides is wrong [S].
- Alerts go to billing admins by email by default. Pub/Sub is optional, via `--notifications-rule-pubsub-topic` (schema version `1.0`) [S].
- A budget only alerts. It does not stop spending. Hard caps need a Pub/Sub-triggered function, which is out of scope.
- Whether the budget compares gross or net-of-credits cost depends on `--credit-types-treatment` (flag exists; default value unverified) [U].

---

## 7. Recommended option B - step-by-step

Parameters: `PROJECT_ID`, `REGION=asia-south1`, `ZONE=asia-south1-a`, `BILLING_ACCOUNT_ID`, `OWNER/REPO`. Run locally with the `membranch` configuration. These commands create resources. The team runs them, not this research task.

```bash
# 0. Local gcloud configuration
gcloud config configurations create membranch
gcloud auth login
gcloud config set project PROJECT_ID
gcloud config set run/region REGION
gcloud config set compute/region REGION
gcloud config set compute/zone ZONE

# 1. Project, billing, APIs
gcloud projects create PROJECT_ID --name=membranch
gcloud billing accounts list
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
gcloud services enable run.googleapis.com compute.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

# 2. Network: custom VPC, one subnet, reserved internal IP for FalkorDB
gcloud compute networks create membranch-vpc --subnet-mode=custom
gcloud compute networks subnets create run-egress --network=membranch-vpc \
  --region=REGION --range=10.20.0.0/24 --enable-private-ip-google-access
gcloud compute addresses create falkordb-ip --region=REGION \
  --subnet=run-egress --addresses=10.20.0.10

# 3. Firewall: 6379 from subnet only; IAP SSH for admin
gcloud compute firewall-rules create allow-run-to-falkordb --network=membranch-vpc \
  --direction=INGRESS --action=allow --rules=tcp:6379 \
  --source-ranges=10.20.0.10/32,10.20.0.0/24 --target-tags=falkordb
gcloud compute firewall-rules create allow-iap-ssh --network=membranch-vpc \
  --direction=INGRESS --action=allow --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 --target-tags=falkordb

# 4. FalkorDB VM with persistent data disk and startup script (section 4.4)
gcloud compute instances create falkordb --zone=ZONE --machine-type=e2-medium \
  --subnet=run-egress --private-network-ip=10.20.0.10 \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB \
  --tags=falkordb \
  --create-disk=name=falkordb-data,size=10GB,type=pd-balanced,auto-delete=no,device-name=falkordb-data \
  --metadata=falkordb-password=CHANGE_ME \
  --metadata-from-file=startup-script=falkordb-startup.sh

# 5. Artifact Registry and service accounts
gcloud artifacts repositories create membranch --repository-format=docker --location=REGION
gcloud iam service-accounts create api-runtime --display-name="API runtime"
gcloud iam service-accounts create gha-deployer --display-name="GitHub deployer"
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:gha-deployer@PROJECT_ID.iam.gserviceaccount.com" --role=roles/run.admin
gcloud artifacts repositories add-iam-policy-binding membranch --location=REGION \
  --member="serviceAccount:gha-deployer@PROJECT_ID.iam.gserviceaccount.com" --role=roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding api-runtime@PROJECT_ID.iam.gserviceaccount.com \
  --member="serviceAccount:gha-deployer@PROJECT_ID.iam.gserviceaccount.com" --role=roles/iam.serviceAccountUser

# 6. WIF pool/provider restricted to one repo (section 5.3)
gcloud iam workload-identity-pools create github-pool --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github-provider --location=global \
  --workload-identity-pool=github-pool --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='OWNER/REPO' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding gha-deployer@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/OWNER/REPO"

# 7. First deploy (manual, before CI is wired): push image, then deploy
gcloud auth configure-docker REGION-docker.pkg.dev --quiet
docker build -t REGION-docker.pkg.dev/PROJECT_ID/membranch/api:first .
docker push REGION-docker.pkg.dev/PROJECT_ID/membranch/api:first
gcloud run deploy membranch-api --image=REGION-docker.pkg.dev/PROJECT_ID/membranch/api:first \
  --region=REGION --service-account=api-runtime@PROJECT_ID.iam.gserviceaccount.com \
  --network=membranch-vpc --subnet=run-egress --vpc-egress=private-ranges-only \
  --min-instances=1 --max-instances=2 --no-cpu-throttling --cpu=1 --memory=1Gi \
  --timeout=3600 --concurrency=40 --allow-unauthenticated \
  --set-env-vars=FALKORDB_HOST=10.20.0.10,FALKORDB_PORT=6379

# 8. Budget alerts (section 6)
gcloud billing budgets create --billing-account=BILLING_ACCOUNT_ID --display-name=membranch-hackathon \
  --budget-amount=150USD --filter-projects=projects/PROJECT_NUMBER \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0

# 9. Then add .github/workflows/deploy.yml (section 5.5) and set GitHub repo variables
```

Verification after step 7:
- `gcloud run services describe membranch-api --format='value(status.url)'` gives the HTTPS URL.
- Hit an SSE endpoint with `curl -N <url>/...` and confirm events arrive live, not in one lump.
- From a Cloud Run request, confirm the graph query reaches FalkorDB (exercises Direct VPC egress and the firewall).

Judging-week checklist:
- Keep `min-instances=1` and `max-instances=2`. A deploy creates a new revision; keep the previous one for rollback.
- Do not `gcloud compute instances stop falkordb` during judging. Data survives in the attached disk.
- Confirm the trial card is valid and the account is not near 90 days or $300 before judging.

---

## 8. Open items (unverified or not checked in this session)

1. Cloud Run pricing: Tier 1 vs Tier 2 for asia-south1, and exact vCPU-s / GiB-s / idle rates. Pricing page truncated.
2. Compute Engine e2-medium and disk prices: from a third-party mirror, not the official table.
3. Static IPv4 pricing (in-use vs reserved): not read from an official page.
4. sslip.io / nip.io on the Public Suffix List, and therefore whether Let's Encrypt rate limits are shared across users.
5. Caddy handling of the Let's Encrypt `shortlived` IP certificate profile.
6. Cloud Run streaming / SSE buffering on the deployed service: needs a live test.
7. Migrate-containers guide: full startup-script example was truncated.
8. WIF binding syntax: confirm against the official Workload Identity Federation docs; the one in 5.3 is from third-party guides.
9. Whether Indian-issued cards are accepted for the trial, and the default asia-south1 CPU quota for a new project.
10. Concurrency default for Cloud Run (recalled as 80).
11. FalkorDB data path inside the container (`/var/lib/falkordb/data` vs `/data`).

---

## Sources

Official (Google Cloud):
- https://docs.cloud.google.com/free/docs/free-trial [V]
- https://docs.cloud.google.com/free/docs/free-cloud-features [V]
- https://docs.cloud.google.com/run/docs/configuring/request-timeout [V]
- https://docs.cloud.google.com/run/docs/configuring/cpu-allocation [V]
- https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc [V]
- https://docs.cloud.google.com/run/docs/deploying-source-code [S]
- https://docs.cloud.google.com/compute/docs/containers/prepare-for-container-agent-shutdown [V]
- https://docs.cloud.google.com/compute/docs/containers/migrate-containers [partial]
- https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create [S]
- https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/create-with-container [S, deprecated]
- https://cloud.google.com/run/pricing [truncated, not used]
- https://cloud.google.com/compute/vm-instance-pricing [truncated, not used]

Other official vendor and API sources:
- https://caddyserver.com/docs/automatic-https [V]
- https://letsencrypt.org/docs/rate-limits/ [S]
- https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html [S]
- https://docs.falkordb.com/operations/docker.html [V]
- https://hub.docker.com/v2/repositories/falkordb/falkordb/tags/v4.22.1 [V]
- https://github.com/google-github-actions/auth [V]
- https://github.com/google-github-actions/deploy-cloudrun [V]
- https://api.github.com/repos/google-github-actions/auth/releases/latest (release tags) [V]

Third-party (unverified, used only for estimates):
- https://gcloud-compute.com/asia-south1.html (VM and disk prices) [U]
- https://caddy.community/t/automatic-https-with-ip-address/16532 [S]
- Various WIF how-to guides cited in search snippets [S, U]
