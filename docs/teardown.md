# Cost controls and teardown

This project runs in **demo mode**: the parts that cost money while they run exist only while a demo is on, and are destroyed afterwards. The target is to stay under **$20 a month**.

## The budget

An AWS Budget (`secom-pipeline-monthly`, in the bootstrap stack) caps the whole account at **$20 a month** and emails the maintainer when:

- actual spend passes **50%, 80% and 100%** of the budget
- AWS **forecasts** the month will end over budget

The budget covers the whole account on purpose, so it's a real ceiling whatever the spend comes from. The alert email address is kept out of the repo: it lives in `infra/bootstrap/alerts.auto.tfvars`, which is gitignored.

A budget only alerts. It doesn't stop anything. Destroying the runtime stack after each demo is what keeps the bill low.

## What persists and what doesn't

| Stack | Contains | After a demo |
|---|---|---|
| Bootstrap | State bucket, GitHub OIDC provider and roles, AWS Budget, ECR repository (from SECOM-16) | **Kept.** IAM, OIDC and the budget cost nothing or close to it. The bucket holds a few KB of state. |
| Runtime | VPC and network (SECOM-21, free), then Kinesis stream, Fargate producer, Lambda processor, RDS database | **Destroyed** with `runtime-down`, or automatically after 4 hours. The network is free; the services added later bill by the hour. |

## One-button demo mode (SECOM-22)

Two GitHub Actions workflows run on `main` only, with the keyless OIDC apply role:

| Workflow | How to run it | What it does |
|---|---|---|
| `runtime-up` | Actions → **runtime-up** → Run workflow | Plans the runtime stack, writes the plan into the run summary, then applies exactly that plan |
| `runtime-down` | Actions → **runtime-down** → Run workflow | Plans the destroy, shows it, destroys, then lists any resource still tagged `Stack=runtime` |

They share one concurrency lock, so an up and a down never run at the same time. Any failure emails the maintainer through the `secom-alerts` topic.

**Safety net.** `runtime-down` also runs every hour. If the Terraform state shows the stack is up and the last successful `runtime-up` was more than **4 hours** ago (`MAX_UP_HOURS` in the workflow), it destroys the stack and emails the maintainer. It reads "up" from the state itself, so a stack applied from a laptop is caught too (with no `runtime-up` run to date it, it counts as overdue). When the stack is down, the hourly run does nothing.

The tag check signs in with the read-only plan role, because the apply role has no access to the tag API. The tag index can lag a few minutes behind a delete, so a resource listed straight after a destroy is a warning to re-check, not proof something survived.

### Up/down cycles

| Date | Stack contents | Up for | Cost |
|---|---|---|---|
| _first cycle recorded after merge_ | | | |

## Tear down by hand (if the workflows can't run)

```bash
aws login --profile barry
export AWS_PROFILE=barry
cd infra/runtime
terraform init -backend-config=../backend.hcl
terraform plan -destroy -out destroy.tfplan
terraform apply destroy.tfplan
```

Read the plan first: it should list only runtime resources.

## Confirm nothing billable is left

1. List every resource still tagged with this project:

   ```bash
   aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=secom-pipeline --region eu-west-1 --query "ResourceTagMappingList[].ResourceARN"
   ```

   After a teardown, only bootstrap items should remain: the state bucket and the ECR repository. (IAM roles, the OIDC provider and the budget are global and don't appear here.)

2. In the console, open **Billing and Cost Management → Bills** (or Cost Explorer, grouped by service) the next day and check no runtime service is still charging.

## Remove everything (end of the project)

The state bucket has `prevent_destroy`, so this is deliberate and takes a few steps:

1. Destroy the runtime stack (above).
2. Move the bootstrap state back to your laptop, because the bucket that holds it is about to go. In `infra/bootstrap`, create `backend_override.tf` containing `terraform { backend "local" {} }`, then run `terraform init -migrate-state`.
3. In `infra/bootstrap/main.tf`, change `prevent_destroy = true` to `false` and apply.
4. Empty the state bucket, including old versions (S3 console → bucket → **Empty**).
5. Run `terraform destroy` in `infra/bootstrap`.
