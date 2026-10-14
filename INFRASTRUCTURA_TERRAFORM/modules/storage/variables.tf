variable "name" {
  type = string
}

variable "account_id" {
  description = "ID de cuenta AWS; se agrega al nombre para que sea único globalmente"
  type        = string
}

variable "create_scans_bucket" {
  description = "Crear el bucket de fotos de escaneo (depende de la decisión de privacidad 9.6)"
  type        = bool
  default     = true
}

variable "scans_expire_days" {
  description = "Días tras los cuales se borran las fotos de escaneo (S3 expira en días enteros: mínimo 1)"
  type        = number
  default     = 1
}

variable "force_destroy" {
  description = "Permite destruir buckets con objetos (solo dev)"
  type        = bool
  default     = false
}
