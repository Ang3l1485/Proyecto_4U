# Variables de entrada de envs/dev (ARCHITECTURE §5.3). Cada una aparece con el lote que la usa; los valores están
# en terraform.tfvars.

variable "aws_account_id" {
  description = "Única cuenta de AWS en la que puede operar el proveedor (allowed_account_ids)."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id debe ser un ID de cuenta de AWS de 12 dígitos."
  }
}

variable "region" {
  description = "Región de AWS del entorno."
  type        = string
}

variable "proyecto" {
  description = "Nombre del proyecto: primera parte del prefijo de §5.1 y valor de la etiqueta Proyecto."
  type        = string
}

variable "entorno" {
  description = "Nombre del entorno: segunda parte del prefijo de §5.1 y valor de la etiqueta Entorno."
  type        = string
}

variable "cidr_vpc" {
  type        = string
  description = "CIDR de la VPC (§3.2, §5.1)."
}

variable "az_computo" {
  type        = string
  description = "Zona única de las tareas y de RDS (§5.3)."
}

variable "az_secundaria" {
  type        = string
  description = "Segunda zona, solo para publica-b y privada-b (§5.3)."
}

# INF-1.2
variable "rds_clase" {
  type        = string
  description = "Clase de la instancia de RDS."
}

variable "rds_gb" {
  type        = number
  description = "Almacenamiento inicial de RDS en GB (gp3)."
}

variable "rds_gb_max" {
  type        = number
  description = "Tope del autoescalado de almacenamiento de RDS en GB."
}

variable "pg_version" {
  type        = string
  description = "Version mayor de PostgreSQL (solo el numero); RDS elige la menor (>= 17.1 para pgvector 0.8)."
}

# INF-1.3
variable "imagen_inicial_tag" {
  type        = string
  description = "Etiqueta de imagen de las definiciones de tarea que crea Terraform (imagen de prueba bootstrap, §5.11); CI la reemplaza."
}

# INF-2.1
variable "apagado_embedding" {
  type = object({
    zona            = string
    noche           = optional(string)
    inactividad_min = number
  })
  description = "Apagado automatico de embedding (§5.3): zona IANA y cron de la accion nocturna (null = sin ella) y minutos sin uso antes de apagarlo."
}

# INF-3.1
variable "correo_alertas" {
  type        = string
  description = "Correo suscrito al topic de alarmas (§5.3); el mismo de bootstrap/terraform.tfvars (presupuesto)."

  validation {
    condition     = can(regex("^[^@\\s<>]+@[^@\\s<>]+\\.[^@\\s<>]+$", var.correo_alertas))
    error_message = "correo_alertas debe ser una dirección de correo (ARCHITECTURE §5.3)."
  }
}
