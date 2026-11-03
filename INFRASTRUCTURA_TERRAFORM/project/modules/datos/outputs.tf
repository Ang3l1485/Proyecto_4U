output "rds_direccion" {
  description = "Endpoint de la instancia sin puerto (DB_HOST, host del secreto db, output rds_endpoint)."
  value       = aws_db_instance.principal.address
}

output "rds_identificador" {
  description = "Identificador de la instancia (campus-locator-dev-db): dimension DBInstanceIdentifier de las alarmas de RDS (INF-3.1)."
  value       = aws_db_instance.principal.identifier
}

output "rds_puerto" {
  description = "Puerto de la instancia (5432)."
  value       = aws_db_instance.principal.port
}

output "rds_base" {
  description = "Nombre de la base (campus_locator)."
  value       = aws_db_instance.principal.db_name
}

output "rds_usuario" {
  description = "Usuario maestro (campus_app)."
  value       = aws_db_instance.principal.username
}

output "bucket_dataset" {
  description = "Nombre del bucket del dataset."
  value       = aws_s3_bucket.dataset.bucket
}

output "bucket_dataset_arn" {
  description = "ARN del bucket del dataset (politicas IAM de las tareas, INF-1.3)."
  value       = aws_s3_bucket.dataset.arn
}

output "colas" {
  description = "Colas por clave (ingesta, purga, ingesta_dlq, purga_dlq) => { nombre, url, arn }."
  value = merge(
    { for clave, cola in aws_sqs_queue.colas : clave => { nombre = cola.name, url = cola.url, arn = cola.arn } },
    { for clave, cola in aws_sqs_queue.dlq : "${clave}_dlq" => { nombre = cola.name, url = cola.url, arn = cola.arn } },
  )
}
