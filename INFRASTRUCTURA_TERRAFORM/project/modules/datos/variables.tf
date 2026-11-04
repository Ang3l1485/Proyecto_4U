variable "prefijo" {
  type        = string
  description = "Prefijo de nombres sin guion final (campus-locator-dev, ARCHITECTURE 5.1)."
}

variable "cuenta_id" {
  type        = string
  description = "ID de la cuenta de AWS: sufijo del nombre del bucket y aws:SourceAccount de la politica de ingesta."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.cuenta_id))
    error_message = "cuenta_id debe tener 12 digitos."
  }
}

variable "az_computo" {
  type        = string
  description = "Zona de la instancia de RDS (la misma del computo, ADR-INF-03)."
}

variable "subredes_privadas" {
  type        = list(string)
  description = "IDs de privada-a y privada-b (salida subredes_privadas del modulo red), para el grupo de subredes de RDS."

  validation {
    condition     = length(var.subredes_privadas) == 2
    error_message = "subredes_privadas debe tener exactamente dos subredes (una por zona)."
  }
}

variable "sg_rds" {
  type        = string
  description = "ID del grupo de seguridad campus-locator-dev-rds (salida grupos_seguridad[\"rds\"] del modulo red)."
}

variable "rds_clase" {
  type        = string
  description = "Clase de la instancia de RDS (ARCHITECTURE 5.3)."
}

variable "rds_gb" {
  type        = number
  description = "Almacenamiento inicial de RDS en GB (gp3)."
}

variable "rds_gb_max" {
  type        = number
  description = "Tope del autoescalado de almacenamiento de RDS en GB."

  validation {
    condition     = var.rds_gb_max > var.rds_gb
    error_message = "rds_gb_max debe ser mayor que rds_gb."
  }
}

variable "pg_version" {
  type        = string
  description = "Version mayor de PostgreSQL (solo el numero, p. ej. \"17\"); RDS elige la menor por defecto y la actualiza."

  validation {
    condition     = can(regex("^[0-9]+$", var.pg_version))
    error_message = "pg_version es solo la version mayor, sin punto (p. ej. \"17\")."
  }
}

variable "db_password" {
  type        = string
  description = "Contrasena maestra de la base (salida db_password del modulo secretos)."
  sensitive   = true
}
