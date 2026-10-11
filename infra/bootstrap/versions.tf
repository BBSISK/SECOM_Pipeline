terraform {
  # 1.11+ for S3 native state locking (use_lockfile), so no DynamoDB table is needed.
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The rest of the settings (bucket, region, locking) come from ../backend.hcl,
  # which bootstrap.sh writes for your own account. See docs/bootstrap.md.
  backend "s3" {
    key = "bootstrap/terraform.tfstate"
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}
