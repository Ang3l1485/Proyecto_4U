variable "name" {
  type = string
}

variable "recovery_window_in_days" {
  description = "0 permite borrar de inmediato (dev); 7-30 en prod"
  type        = number
  default     = 7
}
