#!/usr/bin/env bash
# One-time GCP setup for Membranch (ADR 0005): Cloud Run API + private FalkorDB VM over Direct VPC egress.
#
#   cp deploy/gcp/membranch.env.example deploy/gcp/membranch.env   # fill in
#   deploy/gcp/setup.sh infra          # project, APIs, VPC, firewall, FalkorDB VM, registry, SAs, secrets, WIF
#   deploy/gcp/setup.sh llm-secrets    # store GROQ/GEMINI keys in Secret Manager (prompts, nothing echoed)
#   deploy/gcp/setup.sh first-deploy   # Cloud Build the image + create the Cloud Run service
#   deploy/gcp/setup.sh github         # set repo variables so .github/workflows/deploy.yml deploys on push
#   deploy/gcp/setup.sh budget         # budget alerts at 50/80/100 %
#   deploy/gcp/setup.sh status         # URL, revision, VM state
#
# Safety: every gcloud call runs under the dedicated "membranch" configuration with the project pinned,
# so nothing can land in another (e.g. work) project that happens to be your default.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/membranch.env"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (copy membranch.env.example)"; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${ACCOUNT:?}" "${PROJECT_ID:?}" "${REGION:?}" "${ZONE:?}" "${GITHUB_REPO:?}"

export CLOUDSDK_ACTIVE_CONFIG_NAME=membranch
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"
gcloud config configurations describe membranch >/dev/null 2>&1 \
  || gcloud config configurations create membranch --no-activate >/dev/null
gcloud config set account "$ACCOUNT" >/dev/null
gcloud config set project "$PROJECT_ID" >/dev/null 2>&1 || true
gcloud config set run/region "$REGION" >/dev/null
gcloud config set compute/region "$REGION" >/dev/null
gcloud config set compute/zone "$ZONE" >/dev/null
if ! gcloud auth list --filter="account=$ACCOUNT" --format="value(account)" | grep -q .; then
  gcloud auth login "$ACCOUNT"
fi
[[ "$(gcloud config get account 2>/dev/null)" == "$ACCOUNT" ]] || { echo "account mismatch, aborting"; exit 1; }

SERVICE=membranch-api
VPC=membranch-vpc
SUBNET=run-egress
FALKOR_IP=10.20.0.10
AR_REPO=membranch
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO/api"
RUNTIME_SA="api-runtime@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOY_SA="gha-deployer@$PROJECT_ID.iam.gserviceaccount.com"

exists() { "$@" >/dev/null 2>&1; }
step() { printf '\n== %s\n' "$*"; }

infra() {
  step "project + billing"
  exists gcloud projects describe "$PROJECT_ID" || gcloud projects create "$PROJECT_ID" --name=membranch
  : "${BILLING_ACCOUNT_ID:?set BILLING_ACCOUNT_ID}"
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID" >/dev/null
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

  step "APIs"
  gcloud services enable run.googleapis.com compute.googleapis.com artifactregistry.googleapis.com \
    cloudbuild.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
    secretmanager.googleapis.com

  step "network: VPC, /24 subnet (Direct VPC egress needs >= /26), reserved FalkorDB IP"
  exists gcloud compute networks describe $VPC || gcloud compute networks create $VPC --subnet-mode=custom
  exists gcloud compute networks subnets describe $SUBNET --region="$REGION" \
    || gcloud compute networks subnets create $SUBNET --network=$VPC --region="$REGION" \
         --range=10.20.0.0/24 --enable-private-ip-google-access
  exists gcloud compute addresses describe falkordb-ip --region="$REGION" \
    || gcloud compute addresses create falkordb-ip --region="$REGION" --subnet=$SUBNET --addresses=$FALKOR_IP

  step "firewall: 6379 only from the subnet, SSH only via IAP"
  exists gcloud compute firewall-rules describe allow-run-to-falkordb \
    || gcloud compute firewall-rules create allow-run-to-falkordb --network=$VPC --direction=INGRESS \
         --action=allow --rules=tcp:6379 --source-ranges=10.20.0.0/24 --target-tags=falkordb
  exists gcloud compute firewall-rules describe allow-iap-ssh \
    || gcloud compute firewall-rules create allow-iap-ssh --network=$VPC --direction=INGRESS \
         --action=allow --rules=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=falkordb

  step "secret: FalkorDB password + FALKORDB_URL"
  if ! exists gcloud secrets describe falkordb-url; then
    FALKOR_PW=$(openssl rand -hex 24)
    printf 'redis://:%s@%s:6379' "$FALKOR_PW" "$FALKOR_IP" \
      | gcloud secrets create falkordb-url --data-file=- --replication-policy=automatic
  else
    FALKOR_PW=$(gcloud secrets versions access latest --secret=falkordb-url | sed -E 's#redis://:([^@]+)@.*#\1#')
  fi

  step "FalkorDB VM (e2-medium, Debian 12, separate persistent data disk)"
  if ! exists gcloud compute instances describe falkordb --zone="$ZONE"; then
    gcloud compute instances create falkordb --zone="$ZONE" --machine-type=e2-medium \
      --subnet=$SUBNET --private-network-ip=$FALKOR_IP \
      --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB --tags=falkordb \
      --create-disk=name=falkordb-data,size=10GB,type=pd-balanced,auto-delete=no,device-name=falkordb-data \
      --metadata=falkordb-password="$FALKOR_PW" \
      --metadata-from-file=startup-script="$HERE/falkordb-startup.sh"
  fi

  step "Artifact Registry + service accounts"
  exists gcloud artifacts repositories describe $AR_REPO --location="$REGION" \
    || gcloud artifacts repositories create $AR_REPO --repository-format=docker --location="$REGION"
  exists gcloud iam service-accounts describe "$RUNTIME_SA" \
    || gcloud iam service-accounts create api-runtime --display-name="Membranch API runtime"
  exists gcloud iam service-accounts describe "$DEPLOY_SA" \
    || gcloud iam service-accounts create gha-deployer --display-name="GitHub Actions deployer"
  gcloud secrets add-iam-policy-binding falkordb-url --member="serviceAccount:$RUNTIME_SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOY_SA" \
    --role=roles/run.admin --condition=None >/dev/null
  gcloud artifacts repositories add-iam-policy-binding $AR_REPO --location="$REGION" \
    --member="serviceAccount:$DEPLOY_SA" --role=roles/artifactregistry.writer >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
    --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser >/dev/null

  step "Workload Identity Federation: only $GITHUB_REPO on refs/heads/main may deploy"
  exists gcloud iam workload-identity-pools describe github-pool --location=global \
    || gcloud iam workload-identity-pools create github-pool --location=global --display-name="GitHub Actions"
  exists gcloud iam workload-identity-pools providers describe github-provider --location=global \
      --workload-identity-pool=github-pool \
    || gcloud iam workload-identity-pools providers create-oidc github-provider --location=global \
         --workload-identity-pool=github-pool --display-name="GitHub OIDC" \
         --issuer-uri="https://token.actions.githubusercontent.com" \
         --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
         --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
  gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/$GITHUB_REPO" \
    >/dev/null
  echo "infra ready. next: $0 llm-secrets && $0 first-deploy"
}

llm_secrets() {
  for name in groq-api-key gemini-api-key; do
    read -r -s -p "$name (empty = skip): " val; echo
    [[ -z "$val" ]] && continue
    if exists gcloud secrets describe "$name"; then
      printf '%s' "$val" | gcloud secrets versions add "$name" --data-file=- >/dev/null
    else
      printf '%s' "$val" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic >/dev/null
    fi
    gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:$RUNTIME_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
    echo "stored $name"
  done
}

secrets_flag() {
  local s="FALKORDB_URL=falkordb-url:latest"
  exists gcloud secrets describe groq-api-key && s+=",GROQ_API_KEY=groq-api-key:latest"
  exists gcloud secrets describe gemini-api-key && s+=",GEMINI_API_KEY=gemini-api-key:latest"
  echo "$s"
}

first_deploy() {
  step "build with Cloud Build (no local docker needed)"
  local tag
  tag="$IMAGE:$(git -C "$HERE/../.." rev-parse --short HEAD)"
  (cd "$HERE/../.." && gcloud builds submit --tag "$tag" .)
  step "create/update Cloud Run service (this is the single source of runtime config; CI only swaps the image)"
  gcloud run deploy $SERVICE --image="$tag" --region="$REGION" --service-account="$RUNTIME_SA" \
    --network=$VPC --subnet=$SUBNET --vpc-egress=private-ranges-only \
    --min-instances=1 --max-instances=2 --no-cpu-throttling --cpu=1 --memory=1Gi \
    --timeout=3600 --concurrency=40 --allow-unauthenticated \
    --set-secrets="$(secrets_flag)"
  status
}

github() {
  local number
  number=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  gh variable set GCP_PROJECT_ID --repo "$GITHUB_REPO" --body "$PROJECT_ID"
  gh variable set GCP_REGION --repo "$GITHUB_REPO" --body "$REGION"
  gh variable set GCP_SERVICE --repo "$GITHUB_REPO" --body "$SERVICE"
  gh variable set GCP_DEPLOY_SA --repo "$GITHUB_REPO" --body "$DEPLOY_SA"
  gh variable set GCP_WIF_PROVIDER --repo "$GITHUB_REPO" \
    --body "projects/$number/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
  echo "repo variables set; pushes to main now deploy after CI passes"
}

budget() {
  : "${BILLING_ACCOUNT_ID:?}" "${BUDGET_USD:=150}"
  local number
  number=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  gcloud services enable billingbudgets.googleapis.com
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT_ID" --display-name=membranch-hackathon \
    --budget-amount="${BUDGET_USD}USD" --filter-projects="projects/$number" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0
}

status() {
  echo "url:      $(gcloud run services describe $SERVICE --region="$REGION" --format='value(status.url)' 2>/dev/null)"
  echo "revision: $(gcloud run services describe $SERVICE --region="$REGION" --format='value(status.latestReadyRevisionName)' 2>/dev/null)"
  echo "vm:       $(gcloud compute instances describe falkordb --zone="$ZONE" --format='value(status)' 2>/dev/null)"
}

case "${1:-}" in
  infra) infra ;;
  llm-secrets) llm_secrets ;;
  first-deploy) first_deploy ;;
  github) github ;;
  budget) budget ;;
  status) status ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
