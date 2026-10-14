variable "name" {
  description = "Prefijo de nombres (campus-locator-<env>)"
  type        = string
}

variable "region" {
  type = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  description = "Zonas de disponibilidad (mínimo 2: lo exigen el ALB y el grupo de subredes de RDS)"
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2
    error_message = "Se necesitan al menos 2 zonas de disponibilidad."
  }
}

variable "enable_nat_gateway" {
  type    = bool
  default = false
}
