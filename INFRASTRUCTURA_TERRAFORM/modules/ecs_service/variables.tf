variable "name" {
  description = "Prefijo del ambiente (campus-locator-<env>)"
  type        = string
}

variable "service_name" {
  description = "backend | embedding"
  type        = string
}

variable "cluster_arn" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "assign_public_ip" {
  description = "true cuando las tareas van en subredes públicas sin NAT (necesitan salir a ECR)"
  type        = bool
  default     = false
}

variable "image" {
  description = "URL de ECR + etiqueta"
  type        = string
}

variable "container_port" {
  type = number
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "cpu_architecture" {
  description = "X86_64 o ARM64; debe coincidir con la imagen que construya CI"
  type        = string
  default     = "X86_64"
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "environment" {
  description = "Variables de entorno en claro (nunca secretos)"
  type        = map(string)
  default     = {}
}

variable "ingress_security_group_ids" {
  description = "Security groups autorizados a llegar al puerto del contenedor"
  type        = list(string)
  default     = []
}

variable "target_group_arn" {
  description = "Target group del ALB. null = servicio interno"
  type        = string
  default     = null
}

variable "health_check_grace_seconds" {
  type    = number
  default = 60
}

variable "service_discovery_namespace_id" {
  description = "Namespace de Cloud Map. Solo se usa si enable_service_discovery = true"
  type        = string
  default     = null
}

variable "enable_service_discovery" {
  description = "Registrar el servicio en Cloud Map. Booleano aparte porque namespace_id no se conoce al planificar y no sirve para decidir un count"
  type        = bool
  default     = false
}

variable "attach_task_policy" {
  type    = bool
  default = false
}

variable "task_policy_json" {
  description = "Política IAM del rol de tarea (solo se usa si attach_task_policy = true)"
  type        = string
  default     = null
}

variable "log_retention_days" {
  type    = number
  default = 7
}
