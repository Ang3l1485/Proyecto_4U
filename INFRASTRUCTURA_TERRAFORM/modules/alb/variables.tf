variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "target_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  type    = string
  default = "/health"
}

variable "certificate_arn" {
  description = "Certificado ACM. null = solo HTTP (pruebas, sin dominio todavía)"
  type        = string
  default     = null
}

variable "idle_timeout" {
  description = "Segundos; /localize sube 5 fotos, conviene holgura"
  type        = number
  default     = 60
}

variable "deletion_protection" {
  type    = bool
  default = false
}
