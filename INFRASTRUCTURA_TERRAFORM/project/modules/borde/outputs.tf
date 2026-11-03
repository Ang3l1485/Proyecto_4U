output "api_base_url" {
  description = "URL base de la HTTP API, sin barra final (https://<id>.execute-api.<region>.amazonaws.com, 5.2)."
  value       = aws_apigatewayv2_api.principal.api_endpoint
}

output "api_id" {
  description = "ID de la HTTP API: dimension ApiId de la alarma de 5xx (modulo observabilidad, INF-3.1)."
  value       = aws_apigatewayv2_api.principal.id
}
