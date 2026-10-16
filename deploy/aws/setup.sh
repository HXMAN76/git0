#!/usr/bin/env bash
# One-time AWS setup for Membranch (ADR 0006): one EC2 host running Caddy (HTTPS) + api + FalkorDB in compose.
# Public URL: https://<elastic-ip-dashed>.sslip.io. CloudFront in front is optional (USE_CLOUDFRONT=1, needs a
# verified account).
#
#   cp deploy/aws/membranch.env.example deploy/aws/membranch.env   # fill in
#   deploy/aws/setup.sh infra         # ECR, SSM params, IAM, security group, EC2 + EIP, [CloudFront], GitHub OIDC role
#   deploy/aws/setup.sh llm-secrets   # store GROQ/GEMINI keys as SSM SecureStrings (hidden input)
#   deploy/aws/setup.sh github        # set repo variables + trigger the first deploy (deploy-aws.yml)
#   deploy/aws/setup.sh budget        # monthly cost budget with email alerts at 50/80/100 %
#   deploy/aws/setup.sh status        # URL, instance, SSM agent, last deploy
#   deploy/aws/setup.sh teardown      # prints the delete commands (does not run them)
#
# Safety: every call uses AWS_PROFILE from membranch.env, and `infra` asks you to confirm the account id first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/membranch.env"
STATE="$HERE/membranch.state"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (copy membranch.env.example)"; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${AWS_PROFILE:?}" "${REGION:?}" "${GITHUB_REPO:?}" "${INSTANCE_TYPE:=t3.small}" "${USE_CLOUDFRONT:=0}"
export AWS_PROFILE AWS_REGION="$REGION" AWS_PAGER=""
touch "$STATE"
# shellcheck disable=SC1090
source "$STATE"
save() { grep -v "^$1=" "$STATE" > "$STATE.tmp" || true; echo "$1=$2" >> "$STATE.tmp"; mv "$STATE.tmp" "$STATE"; export "$1=$2"; }

NAME=membranch
ECR_REPO=membranch-api
EC2_ROLE=membranch-ec2
DEPLOY_ROLE=membranch-gha-deploy
CACHING_DISABLED=4135ea2d-6df8-44a3-9df3-4b5a84be39ad          # AWS managed cache policy
ALL_VIEWER_EXCEPT_HOST=b689b0a8-53d0-40ab-baf2-68738e2966ac    # AWS managed origin request policy

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
step() { printf '\n== %s\n' "$*"; }

infra() {
  [[ "${ALERT_EMAIL:-}" =~ ^[^@[:space:]]+@[^@[:space:]]+$ && "$ALERT_EMAIL" != "you@example.com" ]] \
    || { echo "set ALERT_EMAIL in $ENV_FILE (used for budget alerts and the ACME/TLS account)"; exit 1; }
  read -r -p "Deploy Membranch into AWS account $ACCOUNT (profile $AWS_PROFILE, $REGION)? [y/N] " ok
  [[ "$ok" == "y" ]] || exit 1

  step "ECR repository (scan on push, keep last 10 images)"
  aws ecr describe-repositories --repository-names $ECR_REPO >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name $ECR_REPO --image-scanning-configuration scanOnPush=true >/dev/null
  aws ecr put-lifecycle-policy --repository-name $ECR_REPO --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null
  save ECR_URI "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$ECR_REPO"

  step "SSM SecureString: FalkorDB password (generated once)"
  aws ssm get-parameter --name /membranch/falkordb-password >/dev/null 2>&1 \
    || aws ssm put-parameter --name /membranch/falkordb-password --type SecureString \
         --value "$(openssl rand -hex 24)" >/dev/null

  step "IAM role for the instance: SSM agent, ECR pull, read /membranch/* params"
  if ! aws iam get-role --role-name $EC2_ROLE >/dev/null 2>&1; then
    aws iam create-role --role-name $EC2_ROLE --assume-role-policy-document \
      '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    aws iam attach-role-policy --role-name $EC2_ROLE --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
    aws iam attach-role-policy --role-name $EC2_ROLE --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
    aws iam create-instance-profile --instance-profile-name $EC2_ROLE >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name $EC2_ROLE --role-name $EC2_ROLE
    sleep 10  # instance profile propagation
  fi
  aws iam put-role-policy --role-name $EC2_ROLE --policy-name membranch-params --policy-document "{
    \"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"ssm:GetParameter\",\"ssm:GetParameters\"],
    \"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter/membranch/*\"}]}"

  step "security group: :80/:443 for Caddy (HTTPS + ACME), nothing else (shell access via SSM, no SSH)"
  VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
  [[ "$VPC_ID" != "None" ]] || { echo "no default VPC in $REGION"; exit 1; }
  SG_ID=$(aws ec2 describe-security-groups --filters Name=group-name,Values=$NAME-origin Name=vpc-id,Values="$VPC_ID" \
          --query 'SecurityGroups[0].GroupId' --output text)
  if [[ "$SG_ID" == "None" ]]; then
    SG_ID=$(aws ec2 create-security-group --group-name $NAME-origin --vpc-id "$VPC_ID" \
            --description "Membranch origin: HTTP/HTTPS for Caddy" --query GroupId --output text)
  fi
  for port in 80 443; do  # duplicate-rule errors on re-run are expected and ignored
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port $port \
      --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
  done
  save SG_ID "$SG_ID"

  step "EC2 ($INSTANCE_TYPE, Amazon Linux 2023, IMDSv2, 20 GB gp3) + Elastic IP"
  if [[ -z "${INSTANCE_ID:-}" ]] || [[ "$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)" =~ ^(terminated|None|)$ ]]; then
    AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
          --query Parameter.Value --output text)
    UD=$(mktemp)
    sed -e "s|__COMPOSE_B64__|$(base64 -w0 "$HERE/compose.prod.yaml")|" \
        -e "s|__CADDY_B64__|$(base64 -w0 "$HERE/Caddyfile")|" \
        -e "s|__DEPLOY_B64__|$(base64 -w0 "$HERE/host-deploy.sh")|" "$HERE/user-data.tpl.sh" > "$UD"
    INSTANCE_ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
      --iam-instance-profile Name=$EC2_ROLE --security-group-ids "$SG_ID" --user-data "file://$UD" \
      --metadata-options HttpTokens=required,HttpEndpoint=enabled \
      --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3}' \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
      --query 'Instances[0].InstanceId' --output text)
    rm -f "$UD"
    save INSTANCE_ID "$INSTANCE_ID"
  fi
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
  if [[ -z "${EIP_ALLOC:-}" ]]; then
    save EIP_ALLOC "$(aws ec2 allocate-address --domain vpc \
      --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)"
  fi
  aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$EIP_ALLOC" >/dev/null
  sleep 5
  ORIGIN=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
           --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
  [[ -n "$ORIGIN" && "$ORIGIN" != "None" ]] || { echo "instance has no public DNS name"; exit 1; }
  save ORIGIN "$ORIGIN"
  EIP=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" --query 'Addresses[0].PublicIp' --output text)
  SITE="${EIP//./-}.sslip.io"
  aws ssm put-parameter --name /membranch/site-address --type String --value "$SITE" --overwrite >/dev/null
  aws ssm put-parameter --name /membranch/acme-email --type String --value "$ALERT_EMAIL" --overwrite >/dev/null
  save PUBLIC_URL "https://$SITE"

  if [[ "$USE_CLOUDFRONT" == 1 && -z "${CF_ID:-}" ]]; then
    step "CloudFront in front of Caddy (HTTPS origin, caching off, 60 s origin read timeout)"
    CFG=$(mktemp)
    cat > "$CFG" <<JSON
{
  "CallerReference": "membranch-$(date +%s)",
  "Comment": "membranch",
  "Enabled": true,
  "PriceClass": "PriceClass_200",
  "HttpVersion": "http2",
  "Origins": {"Quantity": 1, "Items": [{
    "Id": "ec2", "DomainName": "$SITE",
    "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "https-only",
      "OriginReadTimeout": 60, "OriginKeepaliveTimeout": 60,
      "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}}}]},
  "DefaultCacheBehavior": {
    "TargetOriginId": "ec2", "ViewerProtocolPolicy": "redirect-to-https", "Compress": false,
    "CachePolicyId": "$CACHING_DISABLED", "OriginRequestPolicyId": "$ALL_VIEWER_EXCEPT_HOST",
    "AllowedMethods": {"Quantity": 7, "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],
      "CachedMethods": {"Quantity": 2, "Items": ["GET","HEAD"]}}}
}
JSON
    read -r CF_ID CF_DOMAIN < <(aws cloudfront create-distribution --distribution-config "file://$CFG" \
      --query 'Distribution.[Id,DomainName]' --output text)
    rm -f "$CFG"
    [[ -n "${CF_ID:-}" && -n "${CF_DOMAIN:-}" ]] || { echo "CloudFront create failed"; exit 1; }
    save CF_ID "$CF_ID"
    save PUBLIC_URL "https://$CF_DOMAIN"
  fi

  step "GitHub OIDC provider + deploy role (only $GITHUB_REPO on refs/heads/main)"
  OIDC_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
  aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1 \
    || aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
         --client-id-list sts.amazonaws.com >/dev/null
  TRUST="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",
    \"Principal\":{\"Federated\":\"$OIDC_ARN\"},\"Action\":\"sts:AssumeRoleWithWebIdentity\",
    \"Condition\":{\"StringEquals\":{\"token.actions.githubusercontent.com:aud\":\"sts.amazonaws.com\",
    \"token.actions.githubusercontent.com:sub\":\"repo:$GITHUB_REPO:ref:refs/heads/main\"}}}]}"
  if aws iam get-role --role-name $DEPLOY_ROLE >/dev/null 2>&1; then
    aws iam update-assume-role-policy --role-name $DEPLOY_ROLE --policy-document "$TRUST"
  else
    aws iam create-role --role-name $DEPLOY_ROLE --assume-role-policy-document "$TRUST" >/dev/null
  fi
  aws iam put-role-policy --role-name $DEPLOY_ROLE --policy-name membranch-deploy --policy-document "{
    \"Version\":\"2012-10-17\",\"Statement\":[
     {\"Effect\":\"Allow\",\"Action\":\"ecr:GetAuthorizationToken\",\"Resource\":\"*\"},
     {\"Effect\":\"Allow\",\"Action\":[\"ecr:BatchCheckLayerAvailability\",\"ecr:InitiateLayerUpload\",
       \"ecr:UploadLayerPart\",\"ecr:CompleteLayerUpload\",\"ecr:PutImage\",\"ecr:BatchGetImage\"],
       \"Resource\":\"arn:aws:ecr:$REGION:$ACCOUNT:repository/$ECR_REPO\"},
     {\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":[
       \"arn:aws:ec2:$REGION:$ACCOUNT:instance/$INSTANCE_ID\",
       \"arn:aws:ssm:$REGION::document/AWS-RunShellScript\"]},
     {\"Effect\":\"Allow\",\"Action\":[\"ssm:GetCommandInvocation\",\"ssm:ListCommandInvocations\"],\"Resource\":\"*\"}]}"
  save DEPLOY_ROLE_ARN "arn:aws:iam::$ACCOUNT:role/$DEPLOY_ROLE"

  echo; echo "infra ready. URL (live after the first deploy): $PUBLIC_URL"
  echo "next: $0 llm-secrets && $0 github"
}

llm_secrets() {
  for name in groq-api-key gemini-api-key; do
    read -r -s -p "$name (empty = skip): " val; echo
    [[ -z "$val" ]] && continue
    aws ssm put-parameter --name "/membranch/$name" --type SecureString --value "$val" --overwrite >/dev/null
    echo "stored /membranch/$name (takes effect on next deploy)"
  done
}

github() {
  : "${INSTANCE_ID:?run infra first}" "${PUBLIC_URL:?}" "${DEPLOY_ROLE_ARN:?}" "${ECR_URI:?}"
  gh variable set AWS_REGION --repo "$GITHUB_REPO" --body "$REGION"
  gh variable set AWS_DEPLOY_ROLE_ARN --repo "$GITHUB_REPO" --body "$DEPLOY_ROLE_ARN"
  gh variable set AWS_ECR_URI --repo "$GITHUB_REPO" --body "$ECR_URI"
  gh variable set AWS_INSTANCE_ID --repo "$GITHUB_REPO" --body "$INSTANCE_ID"
  gh variable set PUBLIC_URL --repo "$GITHUB_REPO" --body "$PUBLIC_URL"
  echo "repo variables set; triggering the first deploy (main)"
  gh workflow run deploy-aws.yml --repo "$GITHUB_REPO" --ref main
  echo "watch: gh run watch --repo $GITHUB_REPO \$(gh run list --repo $GITHUB_REPO --workflow deploy-aws.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
}

budget() {
  : "${ALERT_EMAIL:?}" "${BUDGET_USD:=30}"
  notif() { echo "{\"Notification\":{\"NotificationType\":\"$1\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":$2,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$ALERT_EMAIL\"}]}"; }
  aws budgets create-budget --account-id "$ACCOUNT" \
    --budget "{\"BudgetName\":\"membranch\",\"BudgetLimit\":{\"Amount\":\"$BUDGET_USD\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
    --notifications-with-subscribers "[$(notif ACTUAL 50),$(notif ACTUAL 80),$(notif FORECASTED 100)]"
  echo "budget membranch: \$$BUDGET_USD/month, alerts to $ALERT_EMAIL"
}

status() {
  echo "account:   $ACCOUNT ($AWS_PROFILE)"
  echo "url:       ${PUBLIC_URL:-?}"
  echo "instance:  ${INSTANCE_ID:-?} $(aws ec2 describe-instances --instance-ids "${INSTANCE_ID:-none}" \
               --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)"
  echo "ssm agent: $(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=${INSTANCE_ID:-none}" \
               --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null)"
  [[ -n "${CF_ID:-}" ]] && echo "cloudfront: $(aws cloudfront get-distribution --id "$CF_ID" --query Distribution.Status --output text 2>/dev/null)"
  [[ -n "${PUBLIC_URL:-}" ]] && curl -fsS --max-time 10 "$PUBLIC_URL/api/health" && echo
}

teardown() {
  cat <<EOF
# Run these by hand after judging (in order). Nothing was deleted.
export AWS_PROFILE=$AWS_PROFILE AWS_REGION=$REGION
# only if USE_CLOUDFRONT=1 created one:
aws cloudfront get-distribution-config --id ${CF_ID:-none}   # set Enabled=false via update-distribution, wait, then:
aws cloudfront delete-distribution --id ${CF_ID:-none} --if-match <ETag>
aws ec2 terminate-instances --instance-ids $INSTANCE_ID
aws ec2 release-address --allocation-id $EIP_ALLOC
aws ec2 delete-security-group --group-id $SG_ID
aws ecr delete-repository --repository-name $ECR_REPO --force
aws ssm delete-parameters --names /membranch/falkordb-password /membranch/groq-api-key /membranch/gemini-api-key /membranch/site-address /membranch/acme-email
aws iam delete-role-policy --role-name $DEPLOY_ROLE --policy-name membranch-deploy && aws iam delete-role --role-name $DEPLOY_ROLE
EOF
}

case "${1:-}" in
  infra) infra ;;
  llm-secrets) llm_secrets ;;
  github) github ;;
  budget) budget ;;
  status) status ;;
  teardown) teardown ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
