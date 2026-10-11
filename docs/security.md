# Security design

## Keyless from the first commit

There are **no long-lived AWS access keys** anywhere in this project: not in GitHub secrets, not in the repo, not in a `.env` file.

| Who | How they sign in to AWS | Lasts |
|---|---|---|
| GitHub Actions | GitHub OIDC token exchanged for a temporary IAM role session | 1 hour |
| The maintainer, from a laptop | `aws login` (browser sign-in with MFA) | A few hours |

### How the GitHub OIDC exchange works

1. A workflow job with `permissions: id-token: write` asks GitHub for a signed OIDC token. The token says which repo, branch or pull request the run belongs to.
2. The job calls AWS STS `AssumeRoleWithWebIdentity` with that token.
3. AWS checks the signature against the IAM OIDC provider for `token.actions.githubusercontent.com`, then checks the token's claims against the role's trust policy (audience `sts.amazonaws.com`, and the exact repo and ref).
4. If both match, AWS returns credentials that expire after one hour.

**Subject claim gotcha.** For this repo GitHub's token names the repo with numeric IDs (`repo:OWNER@<owner_id>/REPO@<repo_id>:...`), not only the plain name. The trust policies accept both spellings; the IDs come from `infra/bootstrap/terraform.tfvars`. The first CI run failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity` until the ID form was added.

The role ARNs are stored as GitHub **repository variables** (`AWS_PLAN_ROLE_ARN`, `AWS_APPLY_ROLE_ARN`), not secrets, because an ARN is an identifier, not a credential.

## The two CI roles

| Role | Who can assume it | What it can do |
|---|---|---|
| `secom-github-plan` | This repo's pull requests and `main` branch | Read-only (`ReadOnlyAccess`), plus creating and deleting the Terraform `.tflock` file so `terraform plan` can lock state |
| `secom-github-apply` | This repo's `main` branch only (merged pull requests) | Create and change the **runtime** stack's resources; read and write only the runtime state |

Guardrails on the apply role:

- **No self-escalation.** It can manage only IAM roles and policies named `secom-*`, and an explicit deny stops it touching the two GitHub roles or the OIDC provider.
- **The state bucket is protected.** An explicit deny stops it changing the bucket's policy, versioning, encryption or lifecycle, or deleting it.
- **One region.** Regional services are denied outside `eu-west-1`.
- **The bootstrap stack is never applied by CI.** The OIDC provider, these roles, the AWS Budget and the state bucket are applied by the maintainer from a laptop, so CI cannot widen its own permissions.

The apply role's service permissions are scoped per service for now and will be tightened to named resources as each one is added.

## Checking it

`.github/workflows/oidc-check.yml` runs on every pull request, signs in with the plan role and runs `aws sts get-caller-identity`. A green run that shows `assumed-role/secom-github-plan/...` proves CI reached AWS without any stored key.

First green run (October 2026): `arn:aws:sts::<account>:assumed-role/secom-github-plan/GitHubActions`.
