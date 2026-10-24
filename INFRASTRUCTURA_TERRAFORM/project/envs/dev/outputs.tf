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
