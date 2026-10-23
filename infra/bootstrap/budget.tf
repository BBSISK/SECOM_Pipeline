# Cost guardrail (SECOM-12).
#
# A monthly cost budget for the whole AWS account, with email alerts.
# Account-wide on purpose: it is the real ceiling on what this account can
# spend without anyone noticing, whichever project the spend comes from.
#
# The alert email address is not committed. It comes from
# infra/bootstrap/alerts.auto.tfvars, which is gitignored (see docs/teardown.md).

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Actual spend crosses 50%, 80% and 100% of the budget.
  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  # AWS forecasts the month will end over budget: the early warning.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in US dollars (demo mode)."
  type        = number
  default     = 20
}

variable "budget_alert_email" {
  description = "Email address for budget and pipeline alerts (SNS topic secom-alerts). Set in alerts.auto.tfvars, which is gitignored."
  type        = string
  sensitive   = true
}
