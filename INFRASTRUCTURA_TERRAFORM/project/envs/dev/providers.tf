# Versiones y proveedor de envs/dev (ARCHITECTURE §3.1, §5.1). CI usa la versión de Terraform fijada en infra.yml.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

# allowed_account_ids: un plan o apply con credenciales de otra cuenta falla al configurar el proveedor (INF-0.2 C4).
# default_tags: las etiquetas obligatorias de §5.1 en todos los recursos que se creen.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Proyecto      = var.proyecto
      Entorno       = var.entorno
      GestionadoPor = "terraform"
      Carpeta       = "INFRASTRUCTURA_TERRAFORM"
    }
  }
}
