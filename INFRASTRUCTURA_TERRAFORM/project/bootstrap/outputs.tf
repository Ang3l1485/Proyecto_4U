# Outputs de bootstrap (ARCHITECTURE §5.2). Se copian a las variables del repositorio de GitHub (§5.9) con
# configurar_github.py y los leen los validadores de INF-0.x.

output "bucket_estado" {
  description = "Bucket del estado remoto de Terraform."
  value       = aws_s3_bucket.estado.id
}

output "rol_gha_terraform_plan_arn" {
  description = "Rol de solo lectura para el plan de los PR (variable AWS_ROL_TERRAFORM_PLAN_ARN)."
  value       = aws_iam_role.gha["terraform_plan"].arn
}

output "rol_gha_terraform_arn" {
  description = "Rol para aplicar Terraform desde el entorno dev (variable AWS_ROL_TERRAFORM_ARN)."
  value       = aws_iam_role.gha["terraform"].arn
}

output "rol_gha_deploy_arn" {
  description = "Rol para desplegar imágenes desde main (variable AWS_ROL_DEPLOY_ARN)."
  value       = aws_iam_role.gha["deploy"].arn
}

output "limite_roles_arn" {
  description = "Permissions boundary que deben llevar todos los roles campus-locator-* que crea envs/dev (INF-1.3)."
  value       = aws_iam_policy.limite_roles.arn
}

output "github_repo" {
  description = "Repositorio de GitHub en el que confían los roles (propietario/nombre)."
  value       = var.github_repo
}
