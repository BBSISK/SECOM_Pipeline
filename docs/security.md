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
| `secom-github-apply` | This repo's `main` branch only (merged pull requests) | Create and change the **runtime** stack's resources; read and write only the runtime state; publish (only) to the `secom-alerts` topic |

Guardrails on the apply role:

- **No self-escalation.** It can manage only IAM roles and policies named `secom-*`, and an explicit deny stops it touching the two GitHub roles or the OIDC provider.
- **The state bucket is protected.** An explicit deny stops it changing the bucket's policy, versioning, encryption or lifecycle, or deleting it.
- **One region.** Regional services are denied outside `eu-west-1`.
- **The bootstrap stack is never applied by CI.** The OIDC provider, these roles, the AWS Budget, the alert topic and the state bucket are applied by the maintainer from a laptop, so CI cannot widen its own permissions.

The apply role's service permissions are scoped per service for now and will be tightened to named resources as each one is added.

## Checking it

The `terraform` job in `.github/workflows/ci.yml` runs on every pull request and every push to `main`. It signs in with the plan role, runs `aws sts get-caller-identity`, then plans the runtime stack. A green run that shows `assumed-role/secom-github-plan/...` proves CI reached AWS without any stored key.

First green run (October 2026): `arn:aws:sts::<account>:assumed-role/secom-github-plan/GitHubActions`.

## Alerts (SECOM-20)

Failures are sent to a human by email instead of waiting in a log.

- **One topic, `secom-alerts`** (Amazon SNS), in the bootstrap stack, with an email subscription. The address lives in the gitignored `alerts.auto.tfvars`, never in the repo, and SNS delivers nothing until the emailed confirmation link is clicked.
- **CI can publish, nothing more.** The apply role has `sns:Publish` on this one topic only. It can't subscribe, unsubscribe or change the topic, so a compromised workflow can't redirect or silence alerts.
- **What sends to it:** the `publish` workflow, when any step after the AWS sign-in fails. The alert names the failing step, the image scan counts (if the scan ran), the commit and a link to the run. If the sign-in itself fails, GitHub's own failed-run email is the notice. Running `publish` by hand with **test_alert** ticked sends a test message. Evidence: [`docs/evidence/secom-20-test-alert.png`](evidence/secom-20-test-alert.png) (cropped above the unsubscribe link, which would let anyone who sees it unsubscribe the maintainer).
- **Encryption:** the AWS-managed SNS key (`alias/aws/sns`), at no cost. **Known limit:** CloudWatch alarms can't publish to a topic encrypted with an AWS-managed key (its key policy can't be edited to let CloudWatch use it). This has to be resolved, at $0, before the CloudWatch alarm stories (SECOM-23 stream lag, SECOM-27 dead-letter queue).

## Shift-left security gate (SECOM-19)

Security checks run on **every pull request**, inside the three CI checks that the `protect-main` ruleset already requires. A finding blocks the merge, so problems are fixed before anything reaches `main` or AWS, not found afterwards.

| Check | Tool | Runs in CI job | Fails the pull request when |
|---|---|---|---|
| Insecure Python patterns | Ruff `S` rules (the Bandit rule set) | `lint-and-test` | Any finding |
| Vulnerable Python dependencies | pip-audit (PyPI advisory database) | `lint-and-test` | Any known vulnerability in `requirements-dev.txt`, including packages pulled in indirectly |
| Terraform and Dockerfile misconfiguration | Trivy `config` | `terraform` | Any HIGH or CRITICAL finding not listed in `.trivyignore.yaml` |
| Dockerfile best practice | Hadolint | `producer-image` | Any warning or error |
| Vulnerable packages in the image | Trivy `image` | `producer-image` | Any HIGH or CRITICAL vulnerability that has a fix |
| Secrets in commits | GitHub secret scanning with push protection | Before the push lands | A push containing a recognised secret is refused |
| Out-of-date dependencies | Dependabot (pip, GitHub Actions, base image) | Weekly | Never fails; opens update pull requests that go through this same gate |

After merge, the publish workflow adds one more check: ECR scans the pushed image and the run fails on any CRITICAL finding.

### What the gate found when it was switched on

The first run of the new checks against the existing code found three real issues, all fixed in the same pull request:

- **pip-audit:** 26 known vulnerabilities in two packages. `pytest` 8.4 (fixed in 9.0.3) and `pillow` 12.x, which `matplotlib` installs indirectly (fixed in 13.0.0). Fix: raised `pytest` to `>=9.0.3` and added a `pillow>=13.0.0` floor in `requirements-dev.txt`.
- **Trivy config, AWS-0345 (HIGH):** the CI apply role allowed `s3:*` on the pipeline's `secom-*` buckets. Fix: replaced with the specific S3 action families the runtime stack needs. This is a bootstrap-stack change, applied by the maintainer, not by CI.
- **Trivy config, AWS-0132 (HIGH):** the Terraform state bucket uses AWS-managed encryption (SSE-S3) rather than a customer-managed KMS key. **Accepted, not fixed** (see below).

Ruff's `S` rules raised two findings in non-test code, both reviewed and marked with a `noqa` comment and the reason: the chaos mode's `random.Random` (needs a repeatable seed and protects no secret) and `price_check.py`'s `subprocess.run` (a fixed argument list with no shell). In tests, `assert`, seeded random data and running the repo's own scripts are allowed through `per-file-ignores` in `pyproject.toml`.

### Accepted findings

Every accepted finding is listed in [`.trivyignore.yaml`](../.trivyignore.yaml) with its reason, so the exception is visible and reviewed rather than silent.

| Finding | Where | Why it is accepted |
|---|---|---|
| AWS-0132: no customer-managed KMS key | Terraform state bucket | A KMS key costs $1 a month plus request charges against a $20 monthly budget. The bucket is already private, versioned, TLS-only and readable only by the maintainer and the two CI roles |
| AWS-0136: SNS topic not on a customer-managed KMS key | `secom-alerts` topic | Same $1-a-month reason. Encrypted with the AWS-managed key, and messages carry only build metadata (step, commit, scan counts, run link). Known limit: CloudWatch alarms can't publish to it; revisit before SECOM-23 / SECOM-27 |

LOW findings are reported but don't fail the build. Current ones: ECR and S3 encrypted with AWS-managed rather than customer-managed keys (same reason as above), no S3 access logging on the state bucket, and no `HEALTHCHECK` in the producer Dockerfile (ECS runs it as a task with no port to probe).

### Supply chain

- **Third-party GitHub Actions are pinned to a commit SHA**, not a tag, with the version in a comment. A tag can be moved to point at different code; a commit SHA cannot. Dependabot proposes SHA updates.
- **Trivy and Hadolint are downloaded as release binaries and checked against a SHA-256 written in `ci.yml`.** If the download doesn't match, the job stops before running it. This is a direct response to the March 2026 compromise of Trivy's own release process and GitHub Actions ([GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23), CVE-2026-33634), where moved tags and a tampered release ran attacker code in other projects' CI. Dependabot can't update these two, so their version and checksum are bumped together by hand.
- **The base image is the official Docker Hub `python:3.12-slim`, pulled through Google's mirror (`mirror.gcr.io`).** It was first pulled from Amazon ECR Public, but ECR Public rate-limits anonymous pulls per IP and shared GitHub runners kept hitting `429 Data limit exceeded`, which failed the required `producer-image` check. The mirror serves the same official image without a login. The Trivy image scan still checks whatever is pulled, on every pull request.

### Proving the gate blocks

To show the gate works, a demonstration pull request changed the producer's base image to an old Python release with known, fixed vulnerabilities. The `producer-image` check failed on the Trivy image scan and the ruleset blocked the merge. The pull request was then closed without merging. Evidence: `docs/evidence/secom-19-trivy-blocked.png`.
