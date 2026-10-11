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

variable "github_owner_id" {
  description = "Numeric GitHub ID of the repo owner (curl -s https://api.github.com/users/<owner> | grep '\"id\"')."
  type        = number
}

variable "github_repo_id" {
  description = "Numeric GitHub ID of the repo (curl -s https://api.github.com/repos/<owner>/<repo> | grep -m1 '\"id\"')."
  type        = number
}
