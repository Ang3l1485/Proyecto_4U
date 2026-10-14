variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "namespace" {
  description = "Dominio DNS interno (ej. campus.internal)"
  type        = string
  default     = "campus.internal"
}

variable "container_insights" {
  type    = bool
  default = false
}
