# Way of working

## Jira

Work is planned in a team-managed Scrum project in Jira (key `SECOM`), in two-week sprints. Epics and stories are written before work starts, each story with acceptance criteria.

## Branches and pull requests

- `main` is protected: changes arrive only through a pull request, and the required CI checks must pass before merge. Nobody pushes to `main` directly.
- One branch per Jira story, named `SECOM-<n>-short-name`, for example `SECOM-10-terraform-bootstrap`.
- The PR title starts with the Jira key, so Jira links the PR to the story.
- Merge with **squash and merge**, then delete the branch.

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

Then open the pull request on GitHub, check CI is green, and merge.
