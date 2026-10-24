# Presupuesto campus-locator-mensual (ARCHITECTURE §3.8 y §5.10; PLAN INF-0.1 C5).
# Budgets escribe directamente al correo (suscriptor EMAIL), sin confirmación.

resource "aws_budgets_budget" "mensual" {
  name         = "${var.proyecto}-mensual"
  budget_type  = "COST"
  limit_amount = format("%.1f", var.presupuesto_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.correo_alertas]
  }

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.correo_alertas]
  }

  notification {
    notification_type          = "FORECASTED"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.correo_alertas]
  }
}
