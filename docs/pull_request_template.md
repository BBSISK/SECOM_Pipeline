## What and why

<!-- One or two sentences. Start the PR title with the Jira key, e.g. "SECOM-10 Terraform bootstrap". -->

Jira: SECOM-

## Checklist

- [ ] Branch is named `SECOM-<n>-short-name`
- [ ] Tests added or updated, and they pass locally (`python -m pytest -q`)
- [ ] `terraform fmt -recursive` run (if `infra/` changed)
- [ ] `terraform plan` read: nothing changes or is destroyed that I didn't expect
- [ ] README updated if anything a reader should know has changed (status table, services, figures)
- [ ] No secrets, keys or account passwords in the diff
