output "host" {
  value = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "name" {
  value = aws_db_instance.this.db_name
}

output "secret_arn" {
  description = "Secreto administrado por RDS con usuario y contraseña"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  value = aws_security_group.this.id
}
