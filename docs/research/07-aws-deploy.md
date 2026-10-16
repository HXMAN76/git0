# 07 - AWS deployment research (hackathon, ap-south-1)

Date: 2026-10-16. Scope: public HTTPS URL, no domain purchase, no cold starts for ~1 week of judging, GitHub Actions auto-deploy on push to `main` via OIDC (no long-lived keys), cheap, FalkorDB persistent and not public.

Legend for every factual claim:
- **[V]** verified in an AWS page fetched on 2026-10-16
- **[S]** seen only in a search-result excerpt, not confirmed on the fetched page
- **[U]** unverified (from memory or third-party aggregator); check before relying on it

No AWS commands were run. All CLI below is a runbook to execute later.

---

## 0. TL;DR

- **Recommended:** one EC2 `t3.medium` (x86_64, 4 GiB) in ap-south-1, Docker Compose running the API and FalkorDB (FalkorDB has no published port), an Elastic IP as the origin, **CloudFront with its default `*.cloudfront.net` HTTPS certificate** in front of it (no domain, no Let's Encrypt), deploy via GitHub OIDC + ECR + SSM Run Command, secrets in SSM Parameter Store.
- **Cost:** about $38/month steady state, or about $4 for a 3-day hackathon and about $10 for the full week of judging.
- **Ruled out:** App Runner (closed to new customers [V]), ECS Express Mode as the default (about 2.5x the cost, ALB has a 60 s idle timeout and cannot host FalkorDB), Lightsail container service (no persistent volume [U], public registries only [V]).
- **Account-plan blocker to check first:** on a new-style **Free plan** account, EC2 usage "can't exceed Free Tier limits" [V]. `t3.medium` is not a free-tier type, so either upgrade to the Paid plan (credits still apply [V]) or use `t3.small` (free-tier eligible for post-2025-07-15 accounts [V], but only 2 GiB RAM).

---

## 1. AWS account plans and credits (2026)

| Item | Status | Tag |
|---|---|---|
| Sign-up credit | $100 granted at account creation, plus up to $100 more by completing activities in the Explore AWS widget | [V] |
| Credit duration | Credits run for up to 6 months or until used, whichever comes first | [V] (aws.amazon.com/free). Some older doc lines say 12 months; the newer pages say 6 |
| Free account plan | No charges while on the plan. Plan ends at 6 months or when credits run out. Only "select services" included. Excludes services that could deplete credits (for example Savings Plans, Reserved Instances) | [V] |
| After Free plan ends | Account closes; resources and data retained 90 days; upgrade within 90 days to keep them. Remaining credits carry to the next bill | [V] |
| Paid account plan | All services; pay only for usage beyond credit balance; account does not close when credits run out; same $100 + $100 credit | [V] |
| Auto-upgrade trap | Free plan auto-upgrades to Paid if the account joins AWS Organizations, Control Tower, APN, Enterprise Agreement, etc. | [V] |
| Free-plan EC2 limit | "You can't exceed your Free Tier limits" for accounts created on/after 2025-07-15 | [V] (EC2 free-tier doc) |
| Eligible EC2 types, accounts created on/after 2025-07-15 | t3.micro, t3.small, t4g.micro, t4g.small, c7i-flex.large, m7i-flex.large | [V] |
| Eligible EC2 types, legacy accounts (before 2025-07-15) | t2.micro, t3.micro only, 12-month term, pay-as-you-go beyond limits | [V] (types). The 750 h/month figure is [U] |
| Public IPv4 free allowance | None stated on the AWS VPC pricing page | [V] (absence) |

Notes:
- The "Paid plan" is probably the right choice for a friend's new account, because it removes the "cannot exceed" blocker and keeps the same credits. Budget alerts (section 8) prevent surprises.
- If the friend's account is an **older account paying real money**, `t3.medium` costs about $33/month (section 9). Use `t3.small` or a Lightsail 2 GB instance if cost matters more than headroom.
- Note that EC2 and EBS are featured on both plans [V].

---

## 2. AWS App Runner (2026)

- App Runner is **closed to new customers** [V] (docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html). Existing customers can keep using it. AWS recommends **Amazon ECS Express Mode** instead [V].
- The closure date (April 30, 2026) appears in a search excerpt of the AWS doc [S]; the fetched text did not show the date.
- Because App Runner is unavailable to a new account, VPC connector and SSE behavior were not researched further.

---

## 3. Amazon ECS Express Mode

What it provisions [V] (docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html):
- Fargate service (awsvpc), task definition, canary deployments, Application Auto Scaling (target-tracking), service-specific CloudWatch log group, metric alarm, ACM certificate, security groups.
- **Application Load Balancer** with an HTTPS :443 listener and host-header rules, plus a target group.
- Default URL format `https://<service-name>.ecs.<region>.on.aws/`, so **HTTPS without a domain** [V] (from search excerpt of the AWS doc [S] and migration guide [V]).
- Defaults: 1 vCPU / 2 GB, desired min 1 task, max 20 tasks, target CPU 60%, health check path `/`, container port 80 (overridable) [V].
- Uses the default VPC's public subnets if none are given (needs at least 2 public subnets in 2 AZs) [V]. Public subnets get an internet-facing ALB and public IP on tasks [V].
- Up to **25 Express services can share one ALB** per VPC [V].
- **Load balancer settings cannot be changed after creation** [V]. The ALB idle timeout therefore stays at its default (60 s, ALB default [V]), so SSE needs data at least every 60 s. ALB idle timeout range is 1–4000 s, default 60 s [V].
- No additional charge for Express Mode itself; you pay for the underlying resources [V].
- The ALB is HTTP/HTTPS/gRPC only, so **FalkorDB (Redis protocol on 6379) cannot sit behind it** [U, known ALB limitation]. FalkorDB would need a separate plain ECS service with Cloud Map and EFS, which is not an Express Mode service.
- Available in ap-south-1? [U]. GovCloud availability was announced June 2026 [S].
- GitHub Action for deploys: `aws-actions/amazon-ecs-deploy-express-service@v1` [V] (from the AWS migration guide example).

Verdict: good fit for the API alone, poor fit for FalkorDB. Cost is about $95/month for both (section 9).

---

## 4. Lightsail

### 4a. Lightsail container service [V unless noted]
- Price tiers: Nano $7 (0.25 vCPU / 512 MB), Micro $10 (0.25 / 1 GB), Small $15 (0.5 / 1 GB), Medium $40 (1 vCPU / 2 GB), Large $80 (2 / 4 GB), XLarge $160 (4 / 8 GB). Billed per hour, max = power x scale.
- Default HTTPS endpoint `<service>.<guid>.<region>.cs.amazonlightsail.com`; HTTP redirects to HTTPS automatically. **No domain needed.**
- 500 GB/month data transfer included per service; overage $0.09/GB [V].
- **Only public container registries are supported**; private images must be pushed from a local machine (`aws lightsail push-container-image`) [V] (FAQ). Pushing from CI is likely possible [U].
- Container services are **not targets for Lightsail load balancers** [V]. Built-in load balancing only.
- **Private connectivity to a Lightsail instance:** no evidence found. Search returned nothing on VPC peering or private endpoints [S, no result]. Assume not possible.
- **Persistent volumes for FalkorDB:** not documented in the FAQ [U]. Treat as not available.
- Also: monitoring has CPU/memory metrics but "alerting ... is currently not supported" [V].

Verdict: not suitable for FalkorDB. Possible for the API alone at $40/month (Medium), which is more than the EC2 option.

### 4b. Lightsail instance [V]
- Linux bundles (USD/month, IPv4): 512 MB $5; 1 GB $7; **2 GB $12** (2 vCPU*, 60 GB SSD, 3 TB transfer); **4 GB $24** (2 vCPU, 80 GB, 4 TB); 8 GB $44 (2 vCPU, 160 GB, 5 TB).
- Mumbai (ap-south-1) gets **half** the listed transfer allowance (for example 2 TB for the 4 GB bundle) [V].
- Lightsail instance HTTPS: no native ALB target and no documented free HTTPS for an instance IP. Options (Caddy plus sslip.io, or a Lightsail load balancer, or a Lightsail CDN distribution) are [U] and not researched in depth.
- Deploys: Lightsail instances are not EC2, so **SSM Run Command is not available** [U]. A keyless GitHub deploy would need `aws lightsail get-instance-access-details` (temporary SSH key), which is [U]. Otherwise SSH keys in GitHub secrets are needed, which conflicts with the no-long-lived-keys requirement.

Verdict: cheapest raw compute ($24 for 4 GB), but the HTTPS front and keyless deploy are weaker than the EC2 + CloudFront + SSM setup.

---

## 5. Single EC2 with Elastic IP

### 5a. Costs [V unless noted]
- Public IPv4: **$0.005 per hour** for both in-use and idle addresses, about $3.60 per address per month at 720 h (AWS example) [V].
- EBS gp3 in ap-south-1: $0.0912 per GB-month [S, aws-pricing.com aggregator, not AWS page].
- t3.medium ap-south-1 on-demand: $0.0448/hour (about $32.70/month at 730 h) [S, Spare Cores and DoiT aggregators both show it; AWS page did not render Mumbai prices].
- t3.small ap-south-1: $0.0224/hour; t4g.small $0.0112/hour (ARM, not usable here because the image is x86_64); t3.micro $0.0112/hour [S].

### 5b. CloudFront in front of the EC2 origin
- **Always Free tier (pay-as-you-go page):** 1 TB data transfer out per month, 10,000,000 HTTP/HTTPS requests per month, 2,000,000 CloudFront Function invocations per month [V]. Eligibility for all accounts not stated [U]; the page does not say it is limited to new accounts.
- Data transfer out after the first 1 TB: US/Canada/Mexico $0.085/GB for the next 9 TB; India column $0.109/GB [V].
- Flat-rate "Free" plan (separate offer): $0/month with 1M requests and 100 GB per month [V]. Not needed.
- **Origin read timeout (response timeout):** default **30 s**, applies to the wait for the first response and to the gap between response packets [V]. Quota range is **1–120 s**, adjustable via Service Quotas [V]. The CDK doc range of 1–180 s is not the CloudFront quota; ignore it.
- **Origin keep-alive timeout:** default 5 s; quota range 1–300 s [V].
- **Response completion timeout:** optional. If not set, CloudFront enforces no maximum on total stream length [V]. Leave it unset for SSE.
- **SSE implication:** the stream can run for minutes as long as packets arrive within 30 s. Send a heartbeat comment (`: ping\n\n`) every 15 s. No quota increase needed.
- **Caching must be off.** Use the managed policy **CachingDisabled**, ID `4135ea2d-6df8-44a3-9df3-4b5a84be39ad` [V] (TTL 0, no cache-key values, compression disabled). Do not use CachingOptimized or UseOriginCacheControlHeaders (the latter has min TTL 0 but keys on cookies). CloudFront honors origin `Cache-Control` headers [S].
- **Origin request policy:** forward viewer headers and query strings. Managed policy `AllViewerExceptHostHeader` is the usual choice [U for its ID]. Verify with `aws cloudfront list-origin-request-policies --type managed` before use.
- **Origin protocol:** HTTP-only on port 80 is acceptable for the hackathon. Lock port 80 to the CloudFront origin-facing managed prefix list `com.amazonaws.global.cloudfront.origin-facing` [V]. Viewer side is HTTPS on `*.cloudfront.net` using the default CloudFront certificate [U, well-known].
- **Gzip caution (API side):** do not let the app's gzip middleware buffer `text/event-stream` responses [U, Starlette GZipMiddleware behavior]. Disable compression for that route.
- Origin DNS: an EC2 public DNS name (`ec2-<ip>.ap-south-1.compute.amazonaws.com`) is a supported origin domain form [V]. Use an Elastic IP so the name does not change on stop/start.
- Caveat: CloudFront `*.cloudfront.net` URLs are random-looking but HTTPS and stable.

### 5c. Caddy + sslip.io / nip.io alternative (not recommended)
- Let's Encrypt limits [V, letsencrypt.org/docs/rate-limits, last updated 2026-08-05]: 50 new certs per registered domain (or per IPv4 address) per 7 days; 5 certs per exact identifier set per 7 days; 5 authorization failures per identifier per hour.
- Whether sslip.io is on the Public Suffix List (which decides what counts as "registered domain") was **not confirmed**. Checked: the ICANN section (chars 0–100k) and the private-section tail (chars 230k–330k) of publicsuffix.org's list, and sslip.io / nip.io were absent from both [V]. Chars 100k–230k were not read [U].
- Recommendation: skip Caddy. CloudFront gives HTTPS with no DNS dependency.

---

## 6. Keyless GitHub Actions deploy (OIDC)

### 6a. OIDC identity provider [V]
- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`
- Thumbprint: **optional**. AWS uses its trusted CA library to verify the GitHub JWKS and only falls back to thumbprints when needed [V] (docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html). `--thumbprint-list` is optional in the CLI [V] (docs.aws.amazon.com/cli/latest/reference/iam/create-open-id-connect-provider.html).

Create it once per account:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

### 6b. Deploy role trust policy [V for claims format, U for exact ARN values]
GitHub's sub claim example for branches is `repo:ORG/REPO:ref:refs/heads/BRANCH` [V]. For `main`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GitHubOidcDeployMain",
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:HXMAN76/git0:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

- Note from GitHub [V]: repos created after 2026-07-15, or opted-in to immutable subject claims, use a `sub` that includes owner and repo IDs. Check the format in the real token before locking the trust policy.
- Keep the repo name's exact casing from the GitHub URL.

### 6c. Deploy role permissions policy [U for exact action list; standard IAM actions]
Least privilege for ECR push plus SSM deploy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "EcrLogin", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    { "Sid": "EcrPush", "Effect": "Allow",
      "Action": ["ecr:BatchCheckLayerAvailability","ecr:BatchGetImage","ecr:CompleteLayerUpload",
                 "ecr:InitiateLayerUpload","ecr:PutImage","ecr:UploadLayerPart","ecr:DescribeImages"],
      "Resource": "arn:aws:ecr:ap-south-1:ACCOUNT_ID:repository/hackapp" },
    { "Sid": "SsmSendToInstance", "Effect": "Allow", "Action": "ssm:SendCommand",
      "Resource": ["arn:aws:ec2:ap-south-1:ACCOUNT_ID:instance/INSTANCE_ID",
                   "arn:aws:ssm:ap-south-1::document/AWS-RunShellScript"] },
    { "Sid": "SsmReadResult", "Effect": "Allow",
      "Action": ["ssm:GetCommandInvocation","ssm:ListCommandInvocations","ec2:DescribeInstances"],
      "Resource": "*" }
  ]
}
```

### 6d. Instance profile (EC2 role) [V for managed policy name from the SSM doc]
- Attach managed policy `AmazonSSMManagedInstanceCore` (SSM agent / Run Command) [V].
- Attach managed policy `AmazonEC2ContainerRegistryReadOnly` for ECR pull [U].
- Inline policy: `ssm:GetParametersByPath` and `ssm:GetParameter` on `arn:aws:ssm:ap-south-1:ACCOUNT_ID:parameter/hackapp/*` and `kms:Decrypt` on the default `aws/ssm` key, or use a customer-managed key [U].

### 6e. Workflow (`.github/workflows/deploy.yml`)
Actions versions verified on 2026-10-16:
- `aws-actions/configure-aws-credentials` latest is **v6.3.0** (published 2026-09-15) [V]. GitHub recommends pinning third-party actions to a commit SHA [V], so pin `@<sha> # v6.3.0` in production.
- `aws-actions/amazon-ecr-login@v2` [V] (AWS migration guide example).
- `docker/build-push-action@v6` [V] (AWS migration guide example).
- `actions/checkout@v6` [V].

```yaml
name: deploy
on:
  push:
    branches: [main]
permissions:
  id-token: write
  contents: read
concurrency:
  group: deploy-main
  cancel-in-progress: false
env:
  AWS_REGION: ap-south-1
  ECR_REPO: hackapp
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: aws-actions/configure-aws-credentials@v6   # pin to SHA in real use
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - id: ecr
        uses: aws-actions/amazon-ecr-login@v2
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: true
          tags: ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPO }}:${{ github.sha }}
      - name: Deploy on EC2 via SSM
        env:
          INSTANCE_ID: ${{ vars.INSTANCE_ID }}
          IMAGE: ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPO }}:${{ github.sha }}
        run: |
          CMD_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name AWS-RunShellScript \
            --comment "deploy ${GITHUB_SHA}" \
            --parameters "commands=[\"/opt/hackapp/deploy.sh $IMAGE\"]" \
            --query 'Command.CommandId' --output text)
          aws ssm wait command-executed --command-id "$CMD_ID" --instance-id "$INSTANCE_ID"
```

- `AWS_DEPLOY_ROLE_ARN` and `INSTANCE_ID` are non-secret repo variables (`vars`), not secrets.
- The `aws ssm wait command-executed` subcommand is [U] (standard in the CLI).
- Run Command is **free on EC2** [V].

### 6f. Instance deploy script (`/opt/hackapp/deploy.sh`, installed by user-data)
```bash
#!/bin/bash
set -euo pipefail
IMAGE="$1"
REGION=ap-south-1
cd /opt/hackapp
# Pull secrets from SSM SecureString parameters into a 0600 env file
aws ssm get-parameters-by-path --path /hackapp/ --with-decryption --region "$REGION" \
  --query 'Parameters[*].[Name,Value]' --output text \
  | while IFS=$'\t' read -r name value; do echo "${name##*/}=${value}"; done > .env.tmp
mv .env.tmp .env && chmod 600 .env
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${IMAGE%%/*}"
export APP_IMAGE="$IMAGE"
docker compose pull api
docker compose up -d
docker image prune -f
```

### 6g. docker-compose.yml on the instance
```yaml
services:
  falkordb:
    image: falkordb/falkordb:v4.22.1
    restart: unless-stopped
    mem_limit: 2g
    volumes:
      - falkordb_data:/var/lib/falkordb/data
    # no "ports:" - not reachable from the host network or the internet
    networks: [internal]
  api:
    image: ${APP_IMAGE}
    restart: unless-stopped
    env_file: .env
    depends_on: [falkordb]
    ports:
      - "80:8000"        # app listens on PORT=8000 inside the container
    networks: [internal]
networks:
  internal: {}
volumes:
  falkordb_data: {}
```

- FalkorDB password: the image's handling of a `--requirepass` argument is [U]. Check the FalkorDB docs before relying on it. Pass the password to the app via env, and to FalkorDB via its config. Because FalkorDB is not published, the password is defense in depth.
- Heartbeat: the app's SSE handler must send a comment line at least every 15 s (CloudFront read timeout is 30 s [V]).

### 6h. Security group (origin)
- Inbound TCP 80 from prefix list `com.amazonaws.global.cloudfront.origin-facing` only [V].
- No port 22. Use SSM Session Manager for shell access (AmazonSSMManagedInstanceCore) [V].

---

## 7. Secrets in SSM Parameter Store [V]

- **Standard** parameters (including SecureString): no charge; standard throughput has no per-call charge [V].
- **Advanced** parameters: $0.05 per parameter per month, $0.05 per 10,000 API interactions at higher throughput [V]. Not needed.
- SecureString encryption with the default `aws/ssm` KMS key: no key charge [U].

Create the parameters (values come from the operator's shell, never committed):
```bash
aws ssm put-parameter --region ap-south-1 --name /hackapp/GROQ_API_KEY --type SecureString --value "$GROQ_API_KEY"
aws ssm put-parameter --region ap-south-1 --name /hackapp/FALKORDB_PASSWORD --type SecureString --value "$(openssl rand -base64 24)"
```

Note: `--value "$GROQ_API_KEY"` puts the value on the command line and in shell history. Use `read -s` or `--cli-input-json file://` instead for real use.

---

## 8. Budgets [V]

`aws budgets create-budget` takes `--account-id`, `--budget` (JSON with BudgetName, BudgetLimit, BudgetType COST, TimeUnit MONTHLY) and optional `--notifications-with-subscribers` [V]. Notification fields: NotificationType ACTUAL or FORECASTED, ComparisonOperator, Threshold, ThresholdType PERCENTAGE, SubscriberType EMAIL or SNS [V].

```bash
cat > budget.json <<'EOF'
{ "BudgetName": "hackapp-monthly", "BudgetLimit": { "Amount": "50", "Unit": "USD" },
  "BudgetType": "COST", "TimeUnit": "MONTHLY" }
EOF
cat > notify.json <<'EOF'
[ { "Notification": { "ComparisonOperator": "GREATER_THAN", "NotificationType": "ACTUAL",
      "Threshold": 80, "ThresholdType": "PERCENTAGE" },
    "Subscribers": [ { "Address": "YOUR_EMAIL_HERE", "SubscriptionType": "EMAIL" } ] } ]
EOF
aws budgets create-budget --account-id "$ACCOUNT_ID" --budget file://budget.json \
  --notifications-with-subscribers file://notify.json
```

- Replace `YOUR_EMAIL_HERE` with the operator's address. It is not filled in here.
- Budgets free-tier count (first two budgets free) is [U].
- Budget alerts lag by hours; the Free-tier usage and Billing console are better for real-time checks.

---

## 9. Monthly cost (USD, ap-south-1 unless noted; 730 h/month)

| Option | Components | Monthly | 3-day hackathon | Tags |
|---|---|---|---|---|
| **A. EC2 t3.medium + CloudFront (recommended)** | EC2 $32.70 + EBS gp3 20 GB $1.82 + public IPv4 (EIP) $3.65 + CloudFront $0 (inside always-free 1 TB / 10M req) | **~$38** | ~$4 | EC2 [S], EBS [S], IPv4 [V], CF [V] |
| A-small. EC2 t3.small + CloudFront | EC2 $16.35 + EBS $1.82 + IPv4 $3.65 | ~$22 (2 GiB RAM, tight for FalkorDB + API) | ~$2 | [S]/[V] |
| C1. Lightsail instance 4 GB | $24 + HTTPS front [U] (for example Lightsail LB, not priced here) | $24 + [U] | ~$3 | $24 [V] |
| C2. Lightsail instance 2 GB | $12 + HTTPS front [U] | $12 + [U] | ~$2 | [V] |
| C3. Lightsail container Medium (API only) | $40 + separate DB host | $40 + DB | ~$2 | [V] |
| **D. ECS Express Mode (API) + separate ECS FalkorDB** | Fargate API 1 vCPU/2 GB ~$36 (US-East [U]) + ALB $16.43 [V, US-East] + LCU min ~$5.84 [U minimum] + task public IPv4 $3.65 + ALB ENIs IPv4 2 x $3.65 [U] + FalkorDB Fargate 0.5 vCPU/2 GB ~$21 [U] + EFS/IPv4 ~$5 [U] | **~$95–110** | ~$10 | [U] for Mumbai rates |

Notes:
- Mumbai Fargate and ALB rates were not found; US-East rates used as a floor. Mumbai is typically higher [U].
- All EC2 numbers use the Mumbai on-demand price from aggregators [S]; AWS's own EC2 page did not render Mumbai figures in the fetch.
- Free-tier credits (up to $200) would cover option A for the whole judging window on either plan; option D would eat most of them.

---

## 10. Recommendation and runbook

### 10a. Choose Option A (EC2 + CloudFront + SSM deploy)
Reasons: lowest cost of the serious options, keyless deploy via SSM (no SSH), FalkorDB on the same host with no public port, HTTPS URL with no domain, no cold starts, and one box to back up with an EBS snapshot.

Risks: single host (no HA; acceptable for a 1-week judging window); first deploy needs a human to verify SSE through CloudFront; Free-plan account blocks `t3.medium`.

### 10b. Preconditions
1. Account plan: if on the Free plan, upgrade to Paid (credits stay) **or** use `t3.small`.
2. Confirm the friend's account is not in an AWS Organization (auto-upgrade trap).
3. Confirm GitHub repo `HXMAN76/git0` and branch `main`.

### 10c. Parameterized runbook (run later, not now)
```bash
export AWS_PROFILE=membranch REGION=ap-south-1 GITHUB_REPO=HXMAN76/git0 APP=hackapp
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 1. ECR repository
aws ecr create-repository --repository-name "$APP" --image-scanning-configuration scanOnPush=true --region "$REGION"

# 2. GitHub OIDC provider (once per account)
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com

# 3. Deploy role (trust policy from 6b, permissions from 6c)
aws iam create-role --role-name "$APP-gha-deploy" --assume-role-policy-document file://trust-deploy.json
aws iam put-role-policy --role-name "$APP-gha-deploy" --policy-name deploy --policy-document file://perms-deploy.json

# 4. Instance role + profile
aws iam create-role --role-name "$APP-ec2" --assume-role-policy-document file://trust-ec2.json
aws iam attach-role-policy --role-name "$APP-ec2" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam attach-role-policy --role-name "$APP-ec2" --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
aws iam put-role-policy --role-name "$APP-ec2" --policy-name ssm-params --policy-document file://perms-ec2.json
aws iam create-instance-profile --instance-profile-name "$APP-ec2"
aws iam add-role-to-instance-profile --instance-profile-name "$APP-ec2" --role-name "$APP-ec2"

# 5. Network: default VPC, SG allowing 80 only from CloudFront origin-facing prefix list
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text --region "$REGION")
SUBNET_ID=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" --query 'Subnets[0].SubnetId' --output text --region "$REGION")
PL_ID=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query 'PrefixLists[0].PrefixListId' --output text --region "$REGION")
SG_ID=$(aws ec2 create-security-group --group-name "$APP-origin" --description "$APP origin" --vpc-id "$VPC_ID" --query GroupId --output text --region "$REGION")
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
  --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$PL_ID}]"

# 6. SSM parameters (see section 7 caveats about shell history)
aws ssm put-parameter --region "$REGION" --name /$APP/GROQ_API_KEY --type SecureString --value "<GROQ_API_KEY>"
aws ssm put-parameter --region "$REGION" --name /$APP/FALKORDB_PASSWORD --type SecureString --value "$(openssl rand -base64 24)"

# 7. AMI (AL2023 x86_64, public SSM parameter)  [U: parameter path]
AMI=$(aws ssm get-parameter --region "$REGION" --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)

# 8. Launch the instance (user-data in 10d)
INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type t3.medium \
  --iam-instance-profile Name="$APP-ec2" --security-group-ids "$SG_ID" --subnet-id "$SUBNET_ID" \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3}' \
  --metadata-options HttpTokens=required --user-data file://userdata.sh \
  --query 'Instances[0].InstanceId' --output text)

# 9. Elastic IP (stable CloudFront origin)
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --region "$REGION" --query AllocationId --output text)
aws ec2 associate-address --region "$REGION" --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"
EIP_DNS=$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text | awk -F. '{print "ec2-"$1"-"$2"-"$3"-"$4".ap-south-1.compute.amazonaws.com"}')

# 10. CloudFront distribution: create in the console (origin = $EIP_DNS, HTTP only, port 80,
#     viewer HTTP->HTTPS redirect, cache policy CachingDisabled, origin request policy
#     AllViewerExceptHostHeader, response timeout 30 s default). Or use create-distribution with a config file.
#     Record the distribution domain (dXXXX.cloudfront.net) as the public URL.

# 11. GitHub repo variables (not secrets): AWS_DEPLOY_ROLE_ARN=arn:aws:iam::$ACCOUNT_ID:role/$APP-gha-deploy, INSTANCE_ID=$INSTANCE_ID
gh variable set AWS_DEPLOY_ROLE_ARN --repo "$GITHUB_REPO" --body "arn:aws:iam::$ACCOUNT_ID:role/$APP-gha-deploy"
gh variable set INSTANCE_ID --repo "$GITHUB_REPO" --body "$INSTANCE_ID"

# 12. Budget (section 8)
```

### 10d. EC2 user-data (`userdata.sh`)
```bash
#!/bin/bash
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user
# Docker Compose v2 plugin (pin a version you have verified)
COMPOSE_VERSION=v2.x.x   # [U] set to a verified release
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
mkdir -p /opt/hackapp
# Compose file (section 6g) and deploy script (section 6f) are written here by the operator
# or pulled from the repo at first boot.
systemctl status amazon-ssm-agent --no-pager || true
```

- Amazon Linux 2023 AMIs ship with the SSM agent preinstalled [V] (AWS SSM docs: AWS-provided AL2023 AMIs usually include it). Verify after launch with `aws ssm describe-instance-information` (filter InstanceIds) [U].
- AWS CLI v2 is preinstalled on AL2023 [U], which the deploy script needs.
- The `docker compose` plugin path is [U] (not verified against AL2023 package repos). A distro package may also work.

### 10e. Deploy verification checklist
1. `aws ssm describe-instance-information` shows the instance Online.
2. Manual `send-command` of `AWS-RunShellScript` with `docker ps` returns containers.
3. `curl -I https://<dist>.cloudfront.net/health` returns 200.
4. SSE check: `curl -N https://<dist>.cloudfront.net/<sse-route>` streams heartbeat lines for longer than 60 s.
5. FalkorDB not reachable from outside: `nmap` on the EIP port 6379 is closed.

### 10f. Teardown after judging
- Snapshot the EBS volume first (`aws ec2 create-snapshot`) [U for syntax]. Then stop the instance, or terminate it.
- Release the Elastic IP (idle IPv4 is billed at the same $0.005/h [V]).
- Disable or delete the CloudFront distribution.

---

## 11. Open items and unverified

- Lightsail HTTPS front-end options for an instance and any Lightsail CDN default domain [U].
- Lightsail instance-to-container private networking: no evidence either way [S, no result].
- ECS Express Mode availability in ap-south-1 [U].
- Fargate, ALB, and EBS Mumbai rates (aggregator and US-East numbers used) [U].
- Whether a Free-plan account blocks `t3.medium` launches or only charges for them [U].
- CloudFront Always Free 1 TB applies to all account types (not stated in the fetched text) [U].
- CloudFront managed origin request policy ID for `AllViewerExceptHostHeader` [U].
- FalkorDB image: whether `--requirepass` is accepted as a container command argument [U].
- Docker Compose plugin install path and version on AL2023 [U].
- `aws ssm wait command-executed` CLI syntax [U].
- AWS Budgets free-tier allowance count [U].
- sslip.io Public Suffix List status, chars 100k–230k of the list not read [U].
- GitHub OIDC `sub` claim format for this repo (new-format check, section 6b) [V for the rule, U for this repo's status].

---

## Sources (AWS and GitHub, all fetched or searched 2026-10-16)

- https://aws.amazon.com/free/ (credits, plan comparison, always free)
- https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html (Free plan vs Paid plan, 6 months, 90-day retention)
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html (eligible types before/after 2025-07-15)
- https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html (App Runner closed to new customers)
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html (Express Mode resources and defaults)
- https://aws.amazon.com/blogs/containers/ (Express Mode GitHub Actions blog; search excerpt)
- https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-containers.html (container service FAQ)
- https://aws.amazon.com/lightsail/pricing/ (instance and container prices, Mumbai transfer halving)
- https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/ (Always Free 1 TB, India rates)
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesOrigin.html (origin timeouts, keep-alive)
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cloudfront-limits.html (response timeout 1–120 s, keep-alive 1–300 s)
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html (CachingDisabled ID)
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/LocationsOfEdgeServers.html (origin-facing prefix list)
- https://aws.amazon.com/vpc/pricing/ (public IPv4 $0.005/h)
- https://aws.amazon.com/elasticloadbalancing/pricing/ (ALB $0.0225/h, LCU $0.008, 750 h free for new customers)
- https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-load-balancer-attributes.html (ALB idle timeout 60 s, 1–4000)
- https://letsencrypt.org/docs/rate-limits/ (certificate rate limits)
- https://publicsuffix.org/list/public_suffix_list.dat (sslip.io / nip.io absent from parts read)
- https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html (thumbprint behavior)
- https://docs.aws.amazon.com/cli/latest/reference/iam/create-open-id-connect-provider.html (optional thumbprint)
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws (provider URL, audience, sub claim, id-token: write)
- https://github.com/aws-actions/configure-aws-credentials/releases (v6.3.0 latest, 2026-09-15)
- https://docs.aws.amazon.com/cli/latest/reference/budgets/create-budget.html (create-budget syntax)
- https://docs.aws.amazon.com/systems-manager/latest/userguide/execute-remote-commands.html (Run Command free on EC2)
- https://aws.amazon.com/systems-manager/pricing/ (Parameter Store standard free, advanced $0.05)
- https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-al2.html (SSM agent preinstalled on AL2023 AMIs; search excerpt)
- https://instances.vantage.sh/aws/ec2/t3.medium?region=ap-south-1 (no Mumbai figure found, not used)
- https://aws-pricing.com/ap-south-1.html (Mumbai t3.medium, t3.small, gp3 aggregator rates)
