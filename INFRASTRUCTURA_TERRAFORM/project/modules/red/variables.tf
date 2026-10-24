variable "prefijo" {
  type        = string
  description = "Prefijo de nombres de §5.1 sin guion final (campus-locator-dev)."
}

variable "region" {
  type        = string
  description = "Región de AWS; forma el nombre del servicio del endpoint de S3 (com.amazonaws.<region>.s3)."
}

variable "cidr_vpc" {
  type        = string
  description = "CIDR de la VPC (§3.2). Debe ser una /16: las subredes son sus /24 número 0, 1, 10 y 11."

  validation {
    condition     = can(cidrhost(var.cidr_vpc, 0)) && endswith(var.cidr_vpc, "/16")
    error_message = "cidr_vpc debe ser un bloque IPv4 /16 (p. ej. 10.20.0.0/16)."
  }
}

variable "az_computo" {
  type        = string
  description = "Zona única de las tareas y de RDS: aloja publica-a y privada-a (ADR-INF-03)."
}

variable "az_secundaria" {
  type        = string
  description = "Segunda zona, solo para publica-b y privada-b: el grupo de subredes de RDS exige dos zonas."
}
