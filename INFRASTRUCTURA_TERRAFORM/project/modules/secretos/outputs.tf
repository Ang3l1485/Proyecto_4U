output "db_password" {
  description = "Contrasena maestra de la base; la consume el modulo datos (aws_db_instance)."
  value       = random_password.db.result
  sensitive   = true
}

output "arns" {
  description = "ARN de los tres secretos: { db, jwt, admin_inicial }."
  value       = { for clave, secreto in aws_secretsmanager_secret.secretos : clave => secreto.arn }
}
