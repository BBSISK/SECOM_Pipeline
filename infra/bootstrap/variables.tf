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

variable "noncurrent_state_retention_days" {
  description = "How long old versions of state files are kept before S3 deletes them."
  type        = number
  default     = 90
}

variable "github_owner" {
  description = "GitHub user or organisation that owns the repo (case-sensitive, as GitHub shows it)."
  type        = string
  default     = "BBSISK"
}

variable "github_repo" {
  description = "GitHub repository name (case-sensitive, as GitHub shows it)."
  type        = string
  default     = "SECOM_Pipeline"
}
