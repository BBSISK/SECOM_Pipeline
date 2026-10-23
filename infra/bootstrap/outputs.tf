output "account_id" {
  description = "AWS account ID this stack was applied in (an identifier, not a secret)."
  value       = data.aws_caller_identity.current.account_id
}

output "state_bucket" {
  description = "Name of the S3 bucket holding Terraform state for every stack."
  value       = aws_s3_bucket.tfstate.bucket
}

output "region" {
  description = "Region used for all resources."
  value       = var.region
}

output "github_plan_role_arn" {
  description = "Set as GitHub repository variable AWS_PLAN_ROLE_ARN (an identifier, not a secret)."
  value       = aws_iam_role.github_plan.arn
}

output "github_apply_role_arn" {
  description = "Set as GitHub repository variable AWS_APPLY_ROLE_ARN (an identifier, not a secret)."
  value       = aws_iam_role.github_apply.arn
}

output "producer_repository_url" {
  description = "ECR repository for the replay producer image."
  value       = aws_ecr_repository.producer.repository_url
}

output "alerts_topic_arn" {
  description = "Set as GitHub repository variable ALERTS_TOPIC_ARN (an identifier, not a secret)."
  value       = aws_sns_topic.alerts.arn
}
