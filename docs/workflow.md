# Way of working

## Jira

Work is planned in a team-managed Scrum project in Jira (key `SECOM`), in two-week sprints. Epics and stories are written before work starts, each story with acceptance criteria.

## Branches and pull requests

- `main` is protected: changes arrive only through a pull request, and the required CI checks must pass before merge. Nobody pushes to `main` directly.
- One branch per Jira story, named `SECOM-<n>-short-name`, for example `SECOM-10-terraform-bootstrap`.
- The PR title starts with the Jira key, so Jira links the PR to the story.
- Merge with **squash and merge**, then delete the branch.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to `main`. Two jobs must pass before a pull request can merge (they are required checks in the `protect-main` ruleset):

| Check | What it does |
|---|---|
| `lint-and-test` | `ruff check` and `ruff format --check` (style and common bugs), then `pytest` (unit tests) |
| `terraform` | `terraform fmt -check`, `terraform validate` on both stacks, then signs in to AWS with GitHub OIDC (read-only role, no stored keys) and runs `terraform plan` on the runtime stack. The plan's summary appears on the run page |

Run the same checks locally before pushing:

```bash
python3 -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python3 -m pytest
terraform fmt -check -recursive infra
```

## Typical loop

```bash
git switch main
git pull
git switch -c SECOM-10-terraform-bootstrap
# make the change, run tests
git add -A
git commit -m "SECOM-10 Terraform bootstrap with remote state"
git push -u origin SECOM-10-terraform-bootstrap
```

Then open the pull request on GitHub, wait for both CI checks to go green, and squash-merge.
