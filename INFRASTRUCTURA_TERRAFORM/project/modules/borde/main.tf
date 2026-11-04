# Módulo borde (ARCHITECTURE §3.3, §5.1, §5.7, §5.10; INF-1.4): HTTP API con integración privada por VPC Link hacia el
# servicio de Cloud Map api (SRV), dos rutas con su propio throttling, etapa $default con despliegue automático y
# access logs en JSON. Desde INF-2.1, también el filtro de métricas que cuenta las peticiones a POST /v1/localize.

locals {
  # Formato de §5.10: un objeto JSON por línea. Todos los valores son cadenas (API Gateway escribe "-" cuando un dato
  # no existe, p. ej. integrationLatency en un 429), así cada línea es JSON válido. jsonencode ordena las claves: lo
  # que se guarda en AWS es idéntico a lo que se declara y el plan queda vacío.
  formato_access_logs = jsonencode({
    requestId          = "$context.requestId"
    ip                 = "$context.identity.sourceIp"
    requestTime        = "$context.requestTime"
    httpMethod         = "$context.httpMethod"
    routeKey           = "$context.routeKey"
    path               = "$context.path"
    status             = "$context.status"
    responseLength     = "$context.responseLength"
    integrationLatency = "$context.integrationLatency"
    integrationStatus  = "$context.integrationStatus"
  })

  # Throttling por ruta (§5.10). La general va en default_route_settings; login, en route_settings.
  ruta_general = "ANY /{proxy+}"
  ruta_login   = "POST /v1/auth/login"
  rutas        = toset([local.ruta_general, local.ruta_login])
}

resource "aws_cloudwatch_log_group" "apigw" {
  name              = "/${var.proyecto}/${var.entorno}/apigw"
  retention_in_days = 14
}

# En las dos subredes públicas (§3.3): API Gateway exige subredes de al menos dos zonas para el VPC Link. El grupo
# -vpclink solo tiene salida 8000/tcp hacia -api (§5.7).
resource "aws_apigatewayv2_vpc_link" "principal" {
  name               = "${var.prefijo}-vpclink"
  subnet_ids         = var.subredes_publicas
  security_group_ids = [var.sg_vpclink]
}

# R8: recrear la API cambia su URL (api_base_url, ApiConfig.kt de la app). Para destruirla hay que quitar esto antes.
resource "aws_apigatewayv2_api" "principal" {
  name          = "${var.prefijo}-api"
  protocol_type = "HTTP"
  description   = "API publica de ${var.prefijo} (ARCHITECTURE 3.3)"

  lifecycle {
    prevent_destroy = true
  }
}

# HTTP_PROXY privada: API Gateway resuelve el servicio de Cloud Map api (solo lee registros SRV: IP + 8000) y reenvía
# la petición tal cual. 30 s es el máximo de una HTTP API (R7).
resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.principal.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = var.cloud_map_api_arn
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.principal.id
  payload_format_version = "1.0"
  timeout_milliseconds   = 30000
}

# POST /v1/auth/login existe solo para tener su propio throttling (§3.3); va a la misma integración.
resource "aws_apigatewayv2_route" "rutas" {
  for_each = local.rutas

  api_id    = aws_apigatewayv2_api.principal.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.principal.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 20
    throttling_burst_limit = 40
  }

  route_settings {
    route_key              = local.ruta_login
    throttling_rate_limit  = 2
    throttling_burst_limit = 5
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigw.arn
    format          = local.formato_access_logs
  }

  # route_settings exige que la ruta exista.
  depends_on = [aws_apigatewayv2_route.rutas]
}

# Filtro de métricas de INF-2.1 (§5.1, §5.10): una muestra de valor 1 por cada petición POST /v1/localize que pasa por
# la API (también las que terminan en 4xx, 429 o 5xx: todas son uso). La lee la alarma de inactividad de embedding, que
# vive en computo: el espacio y el nombre de la métrica llegan a los dos módulos desde envs/dev, así ninguno de los dos
# referencia al otro por esto (§5.12). Mira httpMethod y path, no routeKey: /v1/localize entra por ANY /{proxy+}. Los
# valores del formato son cadenas (§5.10), de ahí las comillas.
resource "aws_cloudwatch_log_metric_filter" "localize" {
  name           = "${var.prefijo}-localize"
  log_group_name = aws_cloudwatch_log_group.apigw.name
  pattern        = "{ ($.httpMethod = \"POST\") && ($.path = \"/v1/localize\") }"

  metric_transformation {
    name      = var.metrica_localize.nombre
    namespace = var.metrica_localize.espacio
    value     = "1"
    unit      = "Count"
  }
}
