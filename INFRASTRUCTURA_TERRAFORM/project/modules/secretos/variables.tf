variable "ruta" {
  type        = string
  description = "Prefijo de los nombres de los secretos, sin barra final (campus-locator/dev, ARCHITECTURE 5.1)."

  validation {
    condition     = can(regex("^[a-z0-9-]+/[a-z0-9-]+$", var.ruta))
    error_message = "ruta debe tener la forma <proyecto>/<entorno>, sin barra final."
  }
}

variable "db_host" {
  type        = string
  description = "Direccion de la instancia de RDS, sin puerto (salida rds_direccion del modulo datos)."
}

variable "db_puerto" {
  type        = number
  description = "Puerto de la instancia de RDS (salida rds_puerto del modulo datos)."
}

variable "db_nombre" {
  type        = string
  description = "Nombre de la base (salida rds_base del modulo datos)."
}

variable "db_usuario" {
  type        = string
  description = "Usuario maestro de la base (salida rds_usuario del modulo datos)."
}

variable "admin_inicial_correo" {
  type        = string
  description = "Correo del administrador inicial que crea la tarea migrate (ARCHITECTURE 5.4)."
}
