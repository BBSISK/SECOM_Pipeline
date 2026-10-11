#!/usr/bin/env bash
# First-time setup of remote Terraform state for this project.
#
# The state bucket can't hold its own state before it exists, so this script:
#   1. applies the bootstrap stack with temporary LOCAL state (creates the bucket),
#   2. writes infra/backend.hcl pointing at that bucket,
#   3. moves the bootstrap state into the bucket (terraform init -migrate-state).
# After that, every stack keeps its state in S3 with native locking.
#
# Run once per AWS account, from anywhere:
#   AWS_PROFILE=<your-admin-profile> ./infra/bootstrap/bootstrap.sh
set -euo pipefail

cd "$(dirname "$0")"
BACKEND_FILE="../backend.hcl"
OVERRIDE_FILE="backend_override.tf"

if [[ -f "$BACKEND_FILE" ]]; then
  echo "infra/backend.hcl already exists, so bootstrap has already run."
  echo "For later changes use: terraform init -backend-config=../backend.hcl, then plan and apply."
  exit 1
fi

echo "Checking AWS sign-in..."
aws sts get-caller-identity --query Arn --output text

echo "Step 1/3: create the state bucket using temporary local state"
cat > "$OVERRIDE_FILE" <<'EOF'
# Temporary: removed by bootstrap.sh once the state bucket exists.
terraform {
  backend "local" {}
}
EOF

terraform init -input=false
terraform plan -input=false -out=bootstrap.tfplan

read -r -p "Apply this plan? Type yes to continue: " answer
if [[ "$answer" != "yes" ]]; then
  rm -f "$OVERRIDE_FILE" bootstrap.tfplan
  echo "Stopped. Nothing was created."
  exit 1
fi
terraform apply -input=false bootstrap.tfplan
rm -f bootstrap.tfplan

BUCKET="$(terraform output -raw state_bucket)"
REGION="$(terraform output -raw region)"

echo "Step 2/3: write infra/backend.hcl"
cat > "$BACKEND_FILE" <<EOF
# Written by infra/bootstrap/bootstrap.sh for this AWS account. Not committed (see .gitignore).
bucket       = "${BUCKET}"
region       = "${REGION}"
encrypt      = true
use_lockfile = true
EOF

echo "Step 3/3: move bootstrap state into s3://${BUCKET}"
rm -f "$OVERRIDE_FILE"
terraform init -input=false -migrate-state -force-copy -backend-config="$BACKEND_FILE"

echo
echo "Done. State bucket: ${BUCKET}"
echo "Check: aws s3 ls s3://${BUCKET}/bootstrap/"
echo "The local terraform.tfstate files in infra/bootstrap are now old copies and can be deleted."
