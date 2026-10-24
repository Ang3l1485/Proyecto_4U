# Composición del entorno dev (ARCHITECTURE §4). Aquí solo se componen módulos: ningún módulo llama a otro y las
# dependencias entre ellos pasan por variables y outputs. Cada módulo lo llena el lote indicado (PLAN §2.3).

# Cuenta de las credenciales (output cuenta_id, §5.2). Obliga a configurar el proveedor, y con él a comprobar
# allowed_account_ids, aunque todavía no haya recursos.
data "aws_caller_identity" "actual" {}

# Etiquetas que el proveedor añade a todo recurso (default_tags, §5.1). Nada lo referencia: está para que sus valores
# queden en el estado, donde los comprueba el validador de INF-0.2 (C4b).
# tflint-ignore: terraform_unused_declarations
data "aws_default_tags" "actuales" {}

locals {
  # Prefijo de nombres de §5.1 (campus-locator-dev).
  prefijo = "${var.proyecto}-${var.entorno}"
}

module "red" {
  source = "../../modules/red"

  prefijo       = local.prefijo
  region        = var.region
  cidr_vpc      = var.cidr_vpc
  az_computo    = var.az_computo
  az_secundaria = var.az_secundaria
}

module "datos" { # INF-1.2
  source = "../../modules/datos"
}

module "secretos" { # INF-1.2
  source = "../../modules/secretos"
}

module "computo" { # INF-1.3
  source = "../../modules/computo"
}

module "borde" { # INF-1.4
  source = "../../modules/borde"
}

module "observabilidad" { # INF-3.1
  source = "../../modules/observabilidad"
}

# validacion-0-2 20261024-140400
