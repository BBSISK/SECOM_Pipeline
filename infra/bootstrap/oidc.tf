# Keyless authentication for GitHub Actions (SECOM-11).
#
# GitHub signs a short-lived OIDC token for each workflow run. AWS checks the
# token against this provider and, if the repo and branch match a role's trust
# policy, hands back temporary credentials (1 hour). No AWS access keys exist
# anywhere: not in GitHub secrets, not in the repo, not on a laptop.
#
# Two roles:
#   plan  - read-only. Pull requests (and main) can run `terraform plan`.
#   apply - can change the RUNTIME stack only, and only from the main branch.
# The bootstrap stack (this file, the budget, the state bucket) is applied by a
# person from their own machine, so CI can never widen its own permissions.

locals {
  github_repo_full = "${var.github_owner}/${var.github_repo}"

  # GitHub now puts numeric IDs in the token's subject for some repos:
  #   repo:OWNER@<owner_id>/REPO@<repo_id>:...
  # The IDs never change, even if the repo is renamed, so they are the safer match.
  # Both spellings are accepted so the trust works either way.
  github_subject_repos = [
    local.github_repo_full,
    "${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}",
  ]
  account_id  = data.aws_caller_identity.current.account_id
  name_prefix = "secom"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# ---------------------------------------------------------------------------
# Plan role: read-only
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only this repo: its pull requests, and its main branch.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = flatten([
        for r in local.github_subject_repos : [
          "repo:${r}:pull_request",
          "repo:${r}:ref:refs/heads/main",
        ]
      ])
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name                 = "${local.name_prefix}-github-plan"
  description          = "GitHub Actions (${local.github_repo_full}) read-only role for terraform plan"
  assume_role_policy   = data.aws_iam_policy_document.plan_trust.json
  max_session_duration = 3600
}

# AWS-managed read-only policy: enough for terraform plan to read every resource.
resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# S3 native locking writes a small .tflock object next to the state file,
# so plan needs to create and delete that one object, and nothing else.
data "aws_iam_policy_document" "state_access_plan" {
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
  }

  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/*"]
  }

  statement {
    sid       = "WriteLockFileOnly"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/*.tflock"]
  }
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "terraform-state-lock"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.state_access_plan.json
}

# ---------------------------------------------------------------------------
# Apply role: runtime stack only, main branch only
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "apply_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only pushes to main (i.e. merged pull requests). Never a pull request or other branch.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for r in local.github_subject_repos : "repo:${r}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_apply" {
  name                 = "${local.name_prefix}-github-apply"
  description          = "GitHub Actions (${local.github_repo_full}) role that applies the runtime stack from main"
  assume_role_policy   = data.aws_iam_policy_document.apply_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "apply_permissions" {
  # Terraform state: read/write the runtime state and lock files only.
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
  }

  statement {
    sid       = "RuntimeStateReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/runtime/*"]
  }

  statement {
    sid       = "ReadBootstrapState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/bootstrap/*"]
  }

  # The services the pipeline is built from. Scoped by service; tightened per
  # resource as each one is added in later sprints.
  statement {
    sid = "PipelineServices"
    actions = [
      "kinesis:*",
      "lambda:*",
      "ecs:*",
      "ecr:*",
      "rds:*",
      "sqs:*",
      "logs:*",
      "cloudwatch:*",
      "ec2:Describe*",
      "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute",
      "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute",
      "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway",
      "ec2:AttachInternetGateway", "ec2:DetachInternetGateway",
      "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute",
      "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable",
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress",
      "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress",
      "ec2:CreateVpcEndpoint", "ec2:DeleteVpcEndpoints", "ec2:ModifyVpcEndpoint",
      "ec2:CreateTags", "ec2:DeleteTags",
      "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface",
      "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecrets",
    ]
    resources = ["*"]
  }

  # S3 buckets for the pipeline's own data, named secom-*. Listed by action family rather than "s3:*"
  # (flagged by the Trivy config scan, AWS-0345): no access points, batch jobs, Object Lambda or
  # other S3 features the pipeline does not use.
  statement {
    sid = "PipelineBuckets"
    actions = [
      "s3:CreateBucket", "s3:DeleteBucket",
      "s3:ListBucket", "s3:ListBucketVersions", "s3:ListBucketMultipartUploads",
      "s3:GetBucket*", "s3:PutBucket*", "s3:DeleteBucketPolicy", "s3:DeleteBucketOwnershipControls",
      "s3:GetAccelerateConfiguration", "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration",
      "s3:GetReplicationConfiguration", "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
      "s3:GetIntelligentTieringConfiguration", "s3:GetAnalyticsConfiguration",
      "s3:GetInventoryConfiguration", "s3:GetMetricsConfiguration",
      "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectTagging",
      "s3:PutObject", "s3:PutObjectTagging",
      "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:AbortMultipartUpload",
    ]
    resources = ["arn:aws:s3:::${local.name_prefix}-*", "arn:aws:s3:::${local.name_prefix}-*/*"]
  }

  # IAM: only roles and policies named secom-*, and never the GitHub roles themselves.
  statement {
    sid = "ManagePipelineRoles"
    actions = [
      "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole",
      "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
      "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy", "iam:GetPolicyVersion",
      "iam:CreatePolicyVersion", "iam:DeletePolicyVersion", "iam:ListPolicyVersions",
      "iam:TagPolicy", "iam:UntagPolicy",
      "iam:PassRole",
    ]
    resources = [
      "arn:aws:iam::${local.account_id}:role/${local.name_prefix}-*",
      "arn:aws:iam::${local.account_id}:policy/${local.name_prefix}-*",
    ]
  }

  statement {
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/*"]
  }

  # Guardrail: CI can never change its own roles, the OIDC provider, or the state bucket's settings.
  statement {
    sid    = "DenySelfEscalation"
    effect = "Deny"
    actions = [
      "iam:*",
    ]
    resources = [
      aws_iam_role.github_plan.arn,
      aws_iam_role.github_apply.arn,
      aws_iam_openid_connect_provider.github.arn,
    ]
  }

  statement {
    sid    = "DenyStateBucketChanges"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
      "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration", "s3:PutEncryptionConfiguration",
      "s3:PutBucketPublicAccessBlock",
    ]
    resources = [aws_s3_bucket.tfstate.arn]
  }

  # Guardrail: regional services only in the project's region.
  statement {
    sid    = "DenyOtherRegions"
    effect = "Deny"
    not_actions = [
      "iam:*", "sts:*", "s3:*", "cloudfront:*", "budgets:*", "ce:*", "support:*",
    ]
    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }
}

resource "aws_iam_role_policy" "apply_permissions" {
  name   = "runtime-stack-apply"
  role   = aws_iam_role.github_apply.id
  policy = data.aws_iam_policy_document.apply_permissions.json
}
