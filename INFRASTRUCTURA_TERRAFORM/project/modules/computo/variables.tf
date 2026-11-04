variable "prefijo" {
  type        = string
  description = "Prefijo de nombres sin guion final (campus-locator-dev, ARCHITECTURE 5.1)."
}

variable "proyecto" {
  type        = string
  description = "Nombre del proyecto (campus-locator): repositorios ECR, que no dependen del entorno (5.1)."
}

variable "entorno" {
  type        = string
  description = "Nombre del entorno (dev): APP_ENV y rutas de los log groups (5.1, 5.4)."
}

variable "region" {
  type        = string
  description = "Region de AWS (AWS_REGION de las tareas y awslogs-region)."
}

variable "cuenta_id" {
  type        = string
  description = "ID de la cuenta: aws:SourceAccount de la confianza de los roles de ECS."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.cuenta_id))
    error_message = "cuenta_id debe tener 12 digitos."
  }
}

variable "vpc_id" {
  type        = string
  description = "VPC del espacio de nombres privado de Cloud Map (salida vpc_id del modulo red)."
}

variable "subred_tareas" {
  type        = string
  description = "ID de publica-a: subred de los servicios de Fargate (salida subred_tareas del modulo red)."
}

variable "grupos_seguridad" {
  type        = map(string)
  description = "Salida grupos_seguridad del modulo red; se usan api, worker y embedding (5.7)."

  validation {
    condition     = alltrue([for g in ["api", "worker", "embedding"] : contains(keys(var.grupos_seguridad), g)])
    error_message = "grupos_seguridad debe incluir api, worker y embedding."
  }
}

variable "limite_roles_arn" {
  type        = string
  description = "ARN del permissions boundary campus-locator-limite-roles (output limite_roles_arn de bootstrap, ADR-INF-12)."
}

variable "secretos" {
  type        = map(string)
  description = "ARN de los secretos { db, jwt, admin_inicial } (salida arns del modulo secretos)."

  validation {
    condition     = alltrue([for s in ["db", "jwt", "admin_inicial"] : contains(keys(var.secretos), s)])
    error_message = "secretos debe incluir db, jwt y admin_inicial."
  }
}

variable "db_host" {
  type        = string
  description = "Endpoint de RDS sin puerto (DB_HOST, PGHOST)."
}

variable "db_puerto" {
  type        = number
  description = "Puerto de RDS (DB_PORT, PGPORT)."
}

variable "db_nombre" {
  type        = string
  description = "Nombre de la base (DB_NAME, PGDATABASE)."
}

variable "db_usuario" {
  type        = string
  description = "Usuario de la base (DB_USER, PGUSER)."
}

variable "bucket_dataset" {
  type        = string
  description = "Nombre del bucket del dataset (S3_BUCKET_DATASET)."
}

variable "bucket_dataset_arn" {
  type        = string
  description = "ARN del bucket del dataset (politicas de api y worker, 5.8)."
}

variable "colas" {
  type        = map(object({ nombre = string, url = string, arn = string }))
  description = "Salida colas del modulo datos; se usan ingesta y purga (SQS_URL_* y politicas, 5.8)."

  validation {
    condition     = alltrue([for c in ["ingesta", "purga"] : contains(keys(var.colas), c)])
    error_message = "colas debe incluir ingesta y purga."
  }
}

variable "imagen_inicial_tag" {
  type        = string
  description = "Etiqueta de imagen de las definiciones de tarea que crea Terraform (bootstrap, 5.3); CI la reemplaza."
}

# INF-2.1
variable "metrica_localize" {
  type        = object({ espacio = string, nombre = string })
  description = "Metrica de uso de POST /v1/localize (la publica el filtro de metricas de borde; 5.1). Su espacio es tambien el de EmbeddingEncendidos."
}

variable "apagado_embedding" {
  type = object({
    zona            = string
    noche           = optional(string)
    inactividad_min = number
  })
  description = "Apagado automatico de embedding (5.3): zona horaria IANA y cron de la accion nocturna (null = sin apagado nocturno), y minutos sin uso antes de apagarlo."

  validation {
    condition     = var.apagado_embedding.noche == null || can(regex("^cron\\(.+\\)$", var.apagado_embedding.noche))
    error_message = "apagado_embedding.noche debe ser null o una expresion cron(...) de Application Auto Scaling."
  }

  validation {
    condition = (
      var.apagado_embedding.inactividad_min >= 5 && var.apagado_embedding.inactividad_min <= 1440 &&
      floor(var.apagado_embedding.inactividad_min) == var.apagado_embedding.inactividad_min
    )
    error_message = "apagado_embedding.inactividad_min debe ser un entero entre 5 y 1440 (la alarma evalua un periodo de 60 s por minuto, como mucho un dia)."
  }
}
