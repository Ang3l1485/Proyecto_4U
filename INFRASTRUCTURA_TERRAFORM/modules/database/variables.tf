variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Subredes privadas (mínimo 2 zonas)"
  type        = list(string)
}

variable "engine_major_version" {
  description = "pgvector exige PostgreSQL 15.2 o superior en RDS"
  type        = string
  default     = "16"
}

variable "engine_version" {
  description = "Versión completa; debe pertenecer a engine_major_version"
  type        = string
  default     = "16.15"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "max_allocated_storage_gb" {
  description = "Tope del autoescalado de disco"
  type        = number
  default     = 100
}

variable "db_name" {
  type    = string
  default = "campus"
}

variable "master_username" {
  type    = string
  default = "campus_admin"
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = false
}
