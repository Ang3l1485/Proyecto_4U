output "ecr_urls" {
  description = "URL de los repositorios: { backend, embedding } (outputs ecr_backend_url y ecr_embedding_url)."
  value       = { for clave, repo in aws_ecr_repository.repos : clave => repo.repository_url }
}

output "cluster" {
  description = "Nombre del cluster de ECS (campus-locator-dev)."
  value       = aws_ecs_cluster.principal.name
}

output "cluster_arn" {
  description = "ARN del cluster de ECS: clusterArn de la regla de EventBridge (modulo observabilidad, INF-3.1)."
  value       = aws_ecs_cluster.principal.arn
}

output "servicios" {
  description = "Nombres de los servicios de ECS: { api, worker, embedding }."
  value       = { for clave, servicio in aws_ecs_service.servicios : clave => servicio.name }
}

output "familias_tarea" {
  description = "Familias de definicion de tarea: { api, worker, embedding, migrate, validacion }."
  value       = { for clave, tarea in aws_ecs_task_definition.tareas : clave => tarea.family }
}

output "embedding_dns" {
  description = "Nombre DNS privado de embedding (embedding.campus-locator.local)."
  value       = "${aws_service_discovery_service.servicios["embedding"].name}.${aws_service_discovery_private_dns_namespace.principal.name}"
}

output "cloud_map_api_arn" {
  description = "ARN del servicio de Cloud Map api (SRV): integration_uri de la integracion de API Gateway (modulo borde)."
  value       = aws_service_discovery_service.servicios["api"].arn
}
