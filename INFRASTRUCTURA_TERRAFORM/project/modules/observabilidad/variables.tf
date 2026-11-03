variable "prefijo" {
  type        = string
  description = "Prefijo de nombres sin guion final (campus-locator-dev, ARCHITECTURE 5.1): topic, alarmas y regla."
}

variable "region" {
  type        = string
  description = "Region de AWS (us-east-1): aws:SourceArn de las alarmas en la politica del topic."
}

variable "cuenta_id" {
  type        = string
  description = "ID de la cuenta: condiciones AWS:SourceOwner y aws:SourceAccount de la politica del topic."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.cuenta_id))
    error_message = "cuenta_id debe tener 12 digitos."
  }
}

variable "correo_alertas" {
  type        = string
  description = "Correo de la suscripcion al topic (5.3). SNS le envia un correo de confirmacion y no entrega nada hasta que se confirma."

  validation {
    condition     = can(regex("^[^@\\s<>]+@[^@\\s<>]+\\.[^@\\s<>]+$", var.correo_alertas))
    error_message = "correo_alertas debe ser una direccion de correo."
  }
}

variable "api_id" {
  type        = string
  description = "ID de la HTTP API (salida api_id del modulo borde): dimension ApiId de la alarma de 5xx."
}

variable "cluster" {
  type        = string
  description = "Nombre del cluster de ECS (salida cluster del modulo computo): dimension ClusterName de la alarma de embedding."
}

variable "cluster_arn" {
  type        = string
  description = "ARN del cluster de ECS (salida cluster_arn del modulo computo): clusterArn del patron de la regla de EventBridge."
}

variable "servicios" {
  type        = map(string)
  description = "Salida servicios del modulo computo ({ api, worker, embedding } => nombre): group service:<nombre> de la regla y ServiceName de la alarma de embedding."

  validation {
    condition     = alltrue([for s in ["api", "worker", "embedding"] : contains(keys(var.servicios), s)])
    error_message = "servicios debe incluir api, worker y embedding."
  }
}

variable "colas" {
  type        = map(object({ nombre = string, url = string, arn = string }))
  description = "Salida colas del modulo datos; se usan ingesta_dlq y purga_dlq (QueueName de las alarmas de las DLQ)."

  validation {
    condition     = alltrue([for c in ["ingesta_dlq", "purga_dlq"] : contains(keys(var.colas), c)])
    error_message = "colas debe incluir ingesta_dlq y purga_dlq."
  }
}

variable "rds_identificador" {
  type        = string
  description = "Identificador de la instancia de RDS (salida rds_identificador del modulo datos): dimension DBInstanceIdentifier."
}
