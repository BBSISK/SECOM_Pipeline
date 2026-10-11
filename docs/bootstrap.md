# Bootstrap: remote Terraform state

All infrastructure in this project is Terraform, and its state lives in S3 from the first apply.

## How it is laid out

| Stack | Folder | State key | Lifetime |
|---|---|---|---|
| Bootstrap | `infra/bootstrap` | `bootstrap/terraform.tfstate` | Long-lived: state bucket, then GitHub OIDC roles, AWS Budget and ECR |
| Runtime | `infra/runtime` | `runtime/terraform.tfstate` | Created for a demo, then destroyed |

The state bucket (`secom-pipeline-tfstate-<account-id>`) is:

- **versioned**, so any earlier state can be restored; old versions expire after 90 days
- **encrypted** at rest (SSE-S3)
- **private**: all public access blocked, ACLs disabled, and any non-HTTPS request refused
- protected with `prevent_destroy`, so Terraform won't delete it

Locking uses **S3 native state locking** (`use_lockfile = true`, Terraform 1.11+), so no DynamoDB table is needed. Two applies can't run against the same state at once.

## First-time setup (once per AWS account)

Needs Terraform 1.11 or later, AWS CLI v2, and a signed-in admin profile.

```bash
aws login --profile barry
export AWS_PROFILE=barry
./infra/bootstrap/bootstrap.sh
```

The script applies the bootstrap stack with temporary local state to create the bucket, writes `infra/backend.hcl` for your account, then moves the bootstrap state into the bucket. It shows the plan and asks before creating anything.

## Every time after that

```bash
cd infra/runtime
terraform init -backend-config=../backend.hcl
terraform plan -out runtime.tfplan
terraform apply runtime.tfplan
```

Read the plan's summary line before applying. Stop if anything would change or be destroyed that you didn't expect.

## Running it on your own copy

Fork the repo, sign in to your own AWS account and run the same script. The bucket name includes your account ID, and `infra/backend.hcl` is generated for you, so nothing in the code needs editing.
