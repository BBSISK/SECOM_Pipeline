# Private container registry for the replay producer image (SECOM-16).
#
# Lives in the bootstrap stack because images must survive between demos;
# the runtime stack (ECS Fargate) pulls from it when it is created.
# CI pushes a new image on every merge to main, tagged with the commit SHA,
# using the keyless OIDC apply role.

resource "aws_ecr_repository" "producer" {
  name = "${local.name_prefix}-producer"

  # A tag can never be overwritten: each tag (the commit SHA) always means the same image.
  image_tag_mutability = "IMMUTABLE"

  # Every pushed image is scanned for known vulnerabilities (basic scanning, no extra cost).
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Keep storage (and cost) small: only the 10 most recent images survive.
resource "aws_ecr_lifecycle_policy" "producer" {
  repository = aws_ecr_repository.producer.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Delete untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the 10 most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}
