# Composición del entorno dev (ARCHITECTURE §4). Aquí solo se componen módulos: ningún módulo llama a otro y las
# dependencias entre ellos pasan por variables y outputs. Cada módulo lo llena el lote indicado (PLAN §2.3).

# Cuenta de las credenciales (output cuenta_id, §5.2). Obliga a configurar el proveedor, y con él a comprobar
# allowed_account_ids, aunque todavía no haya recursos.
data "aws_caller_identity" "actual" {}

# Etiquetas que el proveedor añade a todo recurso (default_tags, §5.1). Nada lo referencia: está para que sus valores
# queden en el estado, donde los comprueba el validador de INF-0.2 (C4b).
# tflint-ignore: terraform_unused_declarations
data "aws_default_tags" "actuales" {}

# Outputs de bootstrap (INF-0.1): permissions boundary de los roles de computo (ADR-INF-12). Los roles de CI leen
# todo el bucket de estado; escribir bootstrap/* les esta denegado.
data "terraform_remote_state" "bootstrap" {
  backend = "s3"

  config = {
    bucket = "${var.proyecto}-tfstate-${var.aws_account_id}"
    key    = "bootstrap/terraform.tfstate"
    region = var.region
  }
}

locals {
  # Prefijo de nombres de §5.1 (campus-locator-dev).
  prefijo = "${var.proyecto}-${var.entorno}"

  # Métrica de uso de POST /v1/localize (§5.1, INF-2.1). borde crea el filtro que la publica y computo la lee en la
  # alarma de inactividad de embedding: se define aquí y llega a los dos, así ninguno referencia al otro por ella.
  metrica_localize = {
    espacio = "${var.proyecto}/${var.entorno}"
    nombre  = "LocalizePeticiones"
  }
}

module "red" {
  source = "../../modules/red"

  prefijo       = local.prefijo
  region        = var.region
  cidr_vpc      = var.cidr_vpc
  az_computo    = var.az_computo
  az_secundaria = var.az_secundaria
}

module "datos" {
  source = "../../modules/datos"

  prefijo           = local.prefijo
  cuenta_id         = var.aws_account_id
  az_computo        = var.az_computo
  subredes_privadas = module.red.subredes_privadas
  sg_rds            = module.red.grupos_seguridad["rds"]
  rds_clase         = var.rds_clase
  rds_gb            = var.rds_gb
  rds_gb_max        = var.rds_gb_max
  pg_version        = var.pg_version
  db_password       = module.secretos.db_password
}

module "secretos" {
  source = "../../modules/secretos"

  ruta                 = "${var.proyecto}/${var.entorno}"
  db_host              = module.datos.rds_direccion
  db_puerto            = module.datos.rds_puerto
  db_nombre            = module.datos.rds_base
  db_usuario           = module.datos.rds_usuario
  admin_inicial_correo = "admin@campus.edu.co"
}

module "computo" {
  source = "../../modules/computo"

  prefijo            = local.prefijo
  proyecto           = var.proyecto
  entorno            = var.entorno
  region             = var.region
  cuenta_id          = var.aws_account_id
  vpc_id             = module.red.vpc_id
  subred_tareas      = module.red.subred_tareas
  grupos_seguridad   = module.red.grupos_seguridad
  limite_roles_arn   = data.terraform_remote_state.bootstrap.outputs.limite_roles_arn
  secretos           = module.secretos.arns
  db_host            = module.datos.rds_direccion
  db_puerto          = module.datos.rds_puerto
  db_nombre          = module.datos.rds_base
  db_usuario         = module.datos.rds_usuario
  bucket_dataset     = module.datos.bucket_dataset
  bucket_dataset_arn = module.datos.bucket_dataset_arn
  colas              = module.datos.colas
  imagen_inicial_tag = var.imagen_inicial_tag
  metrica_localize   = local.metrica_localize
  apagado_embedding  = var.apagado_embedding
}

module "borde" {
  source = "../../modules/borde"

  prefijo           = local.prefijo
  proyecto          = var.proyecto
  entorno           = var.entorno
  subredes_publicas = module.red.subredes_publicas
  sg_vpclink        = module.red.grupos_seguridad["vpclink"]
  cloud_map_api_arn = module.computo.cloud_map_api_arn
  metrica_localize  = local.metrica_localize
}

module "observabilidad" { # INF-3.1
  source = "../../modules/observabilidad"

  prefijo           = local.prefijo
  region            = var.region
  cuenta_id         = var.aws_account_id
  correo_alertas    = var.correo_alertas
  api_id            = module.borde.api_id
  cluster           = module.computo.cluster
  cluster_arn       = module.computo.cluster_arn
  servicios         = module.computo.servicios
  colas             = module.datos.colas
  rds_identificador = module.datos.rds_identificador
}

# validacion-0-2 20261024-140400
