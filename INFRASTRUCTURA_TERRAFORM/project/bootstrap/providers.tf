# Proveedor con la cuenta fija (un apply con credenciales de otra cuenta falla) y las etiquetas obligatorias de §5.1.

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
