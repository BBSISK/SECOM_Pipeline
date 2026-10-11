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
