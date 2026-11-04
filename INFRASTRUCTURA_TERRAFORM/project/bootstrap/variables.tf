# Variables de entrada de bootstrap (ARCHITECTURE §5.3, columna «Dónde» = bootstrap o ambos).

variable "aws_account_id" {
  description = "Cuenta de AWS del proyecto. Va a allowed_account_ids del proveedor."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id debe tener 12 dígitos."
  }
}

variable "region" {
  description = "Región de AWS del proyecto."
  type        = string
}

variable "proyecto" {
  description = "Prefijo de los nombres (§5.1)."
  type        = string
}

variable "entorno" {
  description = "Entorno: forma el prefijo de §5.1 y es también el nombre del entorno de GitHub en el que confía gha-terraform."
  type        = string
}

variable "github_repo" {
  description = "Repositorio de GitHub «propietario/nombre», con las mayúsculas exactas de GitHub (IAM compara el sub distinguiendo mayúsculas)."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$", var.github_repo))
    error_message = "github_repo debe ser «propietario/nombre» tal como aparece en GitHub. Está por definir en terraform.tfvars (ARCHITECTURE §5.3)."
  }
}

variable "github_ids" {
  description = <<-EOT
    IDs numéricos inmutables del propietario y del repositorio, solo si el repositorio usa el formato inmutable del
    claim sub de OIDC («propietario@ID/repo@ID»): repos creados, renombrados o transferidos después del 2026-07-15, o
    que activaron la opción. null = formato clásico «propietario/repo». Cómo saberlo: README.md, «Formato del sub».
  EOT
  type = object({
    propietario = number
    repositorio = number
  })
  default = null

  validation {
    condition = var.github_ids == null ? true : (
      var.github_ids.propietario > 0 && floor(var.github_ids.propietario) == var.github_ids.propietario &&
      var.github_ids.repositorio > 0 && floor(var.github_ids.repositorio) == var.github_ids.repositorio
    )
    error_message = "github_ids necesita los IDs enteros (> 0) del propietario y del repositorio, o null."
  }
}

variable "correo_alertas" {
  description = "Correo que recibe los avisos del presupuesto (suscriptor EMAIL de AWS Budgets, sin confirmación)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s<>]+@[^@\\s<>]+\\.[^@\\s<>]+$", var.correo_alertas))
    error_message = "correo_alertas debe ser una dirección de correo. Está por definir en terraform.tfvars (ARCHITECTURE §5.3)."
  }
}

variable "presupuesto_usd" {
  description = "Límite mensual del presupuesto campus-locator-mensual, en USD."
  type        = number

  validation {
    condition     = var.presupuesto_usd > 0
    error_message = "presupuesto_usd debe ser mayor que 0."
  }
}
