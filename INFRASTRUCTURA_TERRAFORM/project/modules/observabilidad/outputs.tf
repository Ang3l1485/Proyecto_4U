output "sns_alertas_arn" {
  description = "ARN del topic campus-locator-dev-alertas (output sns_alertas_arn de envs/dev, 5.2)."
  value       = aws_sns_topic.alertas.arn
}
