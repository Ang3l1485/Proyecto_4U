variable "project" {
  type    = string
  default = "campus-locator"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "enable_nat_gateway" {
  type    = bool
  default = false
}

# --- Interruptor de apagado ---
variable "encendido" {
  description = <<EOT
Interruptor de apagado. false = backend y embedding quedan en 0 tareas (no cobra Fargate); el resto
(ALB, RDS, S3, ECR) sigue existiendo. Uso: terraform apply -var encendido=false
EOT
  type        = bool
  default     = true
}

# --- Cómputo ---
variable "backend_desired_count" {
  type    = number
  default = 1
}

variable "embedding_desired_count" {
  type    = number
  default = 1
}

variable "backend_cpu" {
  type    = number
  default = 512
}

variable "backend_memory" {
  type    = number
  default = 1024
}

variable "embedding_cpu" {
  type    = number
  default = 2048
}

variable "embedding_memory" {
  description = "MB. DINOv2 base + PyTorch en CPU: 4 GB es el punto medio; ajustar al medir (decisión 9.4). Con 2 vCPU Fargate admite de 4096 a 16384"
  type        = number
  default     = 4096
}

variable "image_tag" {
  description = "Etiqueta inicial de las imágenes; luego la fija CI en cada despliegue"
  type        = string
  default     = "latest"
}

variable "embedding_model_name" {
  description = "dinov2_vits14 (pequeño), dinov2_vitb14 (medio, el elegido) o dinov2_vitl14 (grande)"
  type        = string
  default     = "dinov2_vitb14"
}

variable "log_retention_days" {
  type    = number
  default = 7
}

# --- Datos ---
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  type    = bool
  default = false
}

variable "create_scans_bucket" {
  type    = bool
  default = true
}

variable "scans_expire_days" {
  type    = number
  default = 1
}

# --- Borde ---
variable "certificate_arn" {
  description = "Certificado ACM para HTTPS. null hasta la fase 4 (decisión 9.3)"
  type        = string
  default     = null
}

# --- Presupuesto (decisión 9.11) ---
variable "monthly_budget_usd" {
  type    = number
  default = 40
}

variable "budget_alert_email" {
  description = "Correo que recibe las alertas de presupuesto. Vacío = no crear el presupuesto"
  type        = string
  default     = ""
}
