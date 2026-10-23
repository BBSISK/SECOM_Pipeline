# Alert channel (SECOM-20).
#
# One SNS topic that every pipeline failure goes to, with an email subscription.
# The publish workflow sends to it now; CloudWatch alarms (DLQ depth, stream lag)
# will use it later in Sprint 2.
#
# Lives in the bootstrap stack so it survives between demos and the CI apply role
# can't change who gets alerted. The email address is not committed: it comes from
# alerts.auto.tfvars (gitignored), the same file as the budget alerts.
#
# Encrypted with the AWS-managed SNS key (alias/aws/sns), which is free. Known limit:
# CloudWatch alarms can't publish to a topic encrypted with an AWS-managed key, because
# that key's policy can't be edited to let CloudWatch use it. To be resolved, at $0,
# before the alarm stories (SECOM-23, SECOM-27). See docs/security.md.

resource "aws_sns_topic" "alerts" {
  name              = "${local.name_prefix}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

# SNS emails a confirmation link once; nothing is delivered until it is clicked.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.budget_alert_email
}
