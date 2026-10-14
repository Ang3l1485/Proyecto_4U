variable "name" {
  type = string
}

variable "repositories" {
  description = "Un repositorio por servicio"
  type        = list(string)
  default     = ["backend", "embedding"]
}

variable "keep_images" {
  type    = number
  default = 10
}

variable "force_delete" {
  description = "Permite destruir el repositorio aunque tenga imágenes (solo dev)"
  type        = bool
  default     = false
}
