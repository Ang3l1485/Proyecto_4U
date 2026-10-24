output "vpc_id" {
  description = "ID de la VPC campus-locator-dev-vpc."
  value       = aws_vpc.principal.id
}

output "subred_tareas" {
  description = "ID de publica-a: subred de todas las tareas de Fargate (az_computo)."
  value       = aws_subnet.subredes["publica-a"].id
}

output "subredes_publicas" {
  description = "IDs de publica-a y publica-b, en ese orden (VPC Link, INF-1.4)."
  value       = [aws_subnet.subredes["publica-a"].id, aws_subnet.subredes["publica-b"].id]
}

output "subredes_privadas" {
  description = "IDs de privada-a y privada-b, en ese orden (grupo de subredes de RDS, INF-1.2)."
  value       = [aws_subnet.subredes["privada-a"].id, aws_subnet.subredes["privada-b"].id]
}

output "grupos_seguridad" {
  description = "IDs de los grupos de §5.7 por nombre corto: vpclink, api, worker, embedding, rds."
  value       = { for nombre, grupo in aws_security_group.grupos : nombre => grupo.id }
}
