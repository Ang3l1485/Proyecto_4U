# Outputs de envs/dev (ARCHITECTURE §5.2). Cada uno aparece con el lote que crea su recurso.

output "cuenta_id" {
  description = "Cuenta de AWS de las credenciales con que se evaluó el proveedor."
  value       = data.aws_caller_identity.actual.account_id
}

output "subredes_tareas" {
  description = "Lista con el ID de publica-a: subred del run-task de migrate y de la tarea de validacion (§5.2)."
  value       = [module.red.subred_tareas]
}

output "sg_migrate" {
  description = "ID del grupo campus-locator-dev-api, que usan migrate y la tarea de validacion (§5.2, §5.7)."
  value       = module.red.grupos_seguridad["api"]
}

# INF-1.2
output "bucket_dataset" {
  description = "Bucket del dataset."
  value       = module.datos.bucket_dataset
}

output "sqs_ingesta_url" {
  description = "URL de la cola de ingesta."
  value       = module.datos.colas["ingesta"].url
}

output "sqs_purga_url" {
  description = "URL de la cola de purga."
  value       = module.datos.colas["purga"].url
}

output "sqs_ingesta_dlq_url" {
  description = "URL de la DLQ de ingesta."
  value       = module.datos.colas["ingesta_dlq"].url
}

output "sqs_purga_dlq_url" {
  description = "URL de la DLQ de purga."
  value       = module.datos.colas["purga_dlq"].url
}

output "rds_endpoint" {
  description = "Endpoint de RDS sin puerto."
  value       = module.datos.rds_direccion
}

output "secretos" {
  description = "ARN de los secretos: { db, jwt, admin_inicial }."
  value       = module.secretos.arns
}

# INF-1.3
output "ecr_backend_url" {
  description = "URL del repositorio campus-locator/backend (backend.yml)."
  value       = module.computo.ecr_urls["backend"]
}

output "ecr_embedding_url" {
  description = "URL del repositorio campus-locator/embedding (embedding.yml)."
  value       = module.computo.ecr_urls["embedding"]
}

output "ecs_cluster" {
  description = "Nombre del cluster de ECS."
  value       = module.computo.cluster
}

output "ecs_servicios" {
  description = "Servicios de ECS: { api, worker, embedding }."
  value       = module.computo.servicios
}

output "familias_tarea" {
  description = "Familias de definicion de tarea: { api, worker, embedding, migrate, validacion }."
  value       = module.computo.familias_tarea
}

output "embedding_dns" {
  description = "Nombre DNS privado de embedding (Cloud Map)."
  value       = module.computo.embedding_dns
}

# INF-1.4
output "api_base_url" {
  description = "URL base de la API publica, sin barra final (la app le anade /v1)."
  value       = module.borde.api_base_url
}

# INF-3.1
output "sns_alertas_arn" {
  description = "ARN del topic campus-locator-dev-alertas (alarmas y regla de EventBridge, §3.8)."
  value       = module.observabilidad.sns_alertas_arn
}
