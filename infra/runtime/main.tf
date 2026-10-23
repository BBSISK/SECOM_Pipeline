# Runtime stack: everything that costs money while it runs (Kinesis, Fargate,
# Lambda, RDS). It is created for a demo with `terraform apply` and removed
# afterwards with `terraform destroy` (see docs/teardown.md, added in SECOM-12).
#
# Sprint 2 adds the network first (network.tf, SECOM-21): free resources only.

variable "region" {
  description = "AWS region for every resource in this project."
  type        = string
  default     = "eu-west-1"
}

variable "project" {
  description = "Project name, used in resource names and the Project tag."
  type        = string
  default     = "secom-pipeline"
}

data "aws_caller_identity" "current" {}

output "account_id" {
  description = "AWS account ID this stack runs in."
  value       = data.aws_caller_identity.current.account_id
}
