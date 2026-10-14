terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name       = "${var.project}-${var.env}"
  account_id = data.aws_caller_identity.current.account_id
  namespace  = "campus.internal"

  embedding_port = 8001
  backend_port   = 8000

  # En dev las tareas van en subredes públicas (sin NAT) con security groups cerrados.
  tasks_in_public = !var.enable_nat_gateway
  task_subnets    = local.tasks_in_public ? module.network.public_subnet_ids : module.network.private_subnet_ids
}

# ---------------------------------------------------------------------------
# Fase 1: red, imágenes y almacenamiento
# ---------------------------------------------------------------------------
module "network" {
  source = "../../modules/network"

  name               = local.name
  region             = var.region
  vpc_cidr           = var.vpc_cidr
  enable_nat_gateway = var.enable_nat_gateway
}

module "ecr" {
  source = "../../modules/ecr"

  name         = local.name
  force_delete = true # solo dev
}

module "storage" {
  source = "../../modules/storage"

  name                = local.name
  account_id          = local.account_id
  create_scans_bucket = var.create_scans_bucket
  scans_expire_days   = var.scans_expire_days
  force_destroy       = true # solo dev
}

# ---------------------------------------------------------------------------
# Fase 2: datos y secretos
# ---------------------------------------------------------------------------
module "database" {
  source = "../../modules/database"

  name                  = local.name
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  instance_class        = var.db_instance_class
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.db_deletion_protection
}

module "secrets" {
  source = "../../modules/secrets"

  name                    = local.name
  recovery_window_in_days = 0 # dev: se puede destruir y recrear sin esperas
}

# ---------------------------------------------------------------------------
# Fase 3: cómputo
# ---------------------------------------------------------------------------
module "ecs_cluster" {
  source = "../../modules/ecs_cluster"

  name      = local.name
  vpc_id    = module.network.vpc_id
  namespace = local.namespace
}

module "alb" {
  source = "../../modules/alb"

  name              = local.name
  vpc_id            = module.network.vpc_id
  vpc_cidr          = module.network.vpc_cidr
  public_subnet_ids = module.network.public_subnet_ids
  target_port       = local.backend_port
  certificate_arn   = var.certificate_arn
}

# Permisos del backend: los dos buckets, los dos secretos y nada más (ARCHITECTURE 4.1).
data "aws_iam_policy_document" "backend_task" {
  statement {
    sid       = "ObjetosS3"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [for arn in module.storage.bucket_arns : "${arn}/*"]
  }

  statement {
    sid       = "ListarBuckets"
    actions   = ["s3:ListBucket"]
    resources = module.storage.bucket_arns
  }

  statement {
    sid     = "LeerSecretos"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      module.secrets.jwt_secret_arn,
      module.database.secret_arn,
    ]
  }
}

module "backend" {
  source = "../../modules/ecs_service"

  name         = local.name
  service_name = "backend"
  cluster_arn  = module.ecs_cluster.cluster_arn
  vpc_id       = module.network.vpc_id
  subnet_ids   = local.task_subnets

  assign_public_ip = local.tasks_in_public
  image            = "${module.ecr.repository_urls["backend"]}:${var.image_tag}"
  container_port   = local.backend_port
  cpu              = var.backend_cpu
  memory           = var.backend_memory
  desired_count    = var.encendido ? var.backend_desired_count : 0

  environment = {
    APP_ENV               = var.env
    AWS_REGION            = var.region
    DATABASE_HOST         = module.database.host
    DATABASE_PORT         = tostring(module.database.port)
    DATABASE_NAME         = module.database.name
    DATABASE_SECRET_ARN   = module.database.secret_arn
    S3_BUCKET_DATASET     = module.storage.dataset_bucket
    S3_BUCKET_SCANS       = module.storage.scans_bucket
    EMBEDDING_SERVICE_URL = "http://embedding.${local.namespace}:${local.embedding_port}"
    JWT_SECRET_ARN        = module.secrets.jwt_secret_arn
  }

  ingress_security_group_ids = [module.alb.security_group_id]
  target_group_arn           = module.alb.target_group_arn

  attach_task_policy = true
  task_policy_json   = data.aws_iam_policy_document.backend_task.json

  log_retention_days = var.log_retention_days
}

module "embedding" {
  source = "../../modules/ecs_service"

  name         = local.name
  service_name = "embedding"
  cluster_arn  = module.ecs_cluster.cluster_arn
  vpc_id       = module.network.vpc_id
  subnet_ids   = local.task_subnets

  # Interna: sin IP pública propia de entrada; solo necesita salida para tirar la imagen de ECR.
  assign_public_ip = local.tasks_in_public
  image            = "${module.ecr.repository_urls["embedding"]}:${var.image_tag}"
  container_port   = local.embedding_port
  cpu              = var.embedding_cpu
  memory           = var.embedding_memory
  desired_count    = var.encendido ? var.embedding_desired_count : 0

  environment = {
    APP_ENV    = var.env
    MODEL_NAME = var.embedding_model_name
    PORT       = tostring(local.embedding_port)
  }

  # Solo el backend puede llamar al embedding.
  ingress_security_group_ids     = [module.backend.security_group_id]
  service_discovery_namespace_id = module.ecs_cluster.namespace_id

  log_retention_days = var.log_retention_days
}

# backend -> RDS (la única regla de entrada de la base).
resource "aws_vpc_security_group_ingress_rule" "db_from_backend" {
  security_group_id            = module.database.security_group_id
  referenced_security_group_id = module.backend.security_group_id
  ip_protocol                  = "tcp"
  from_port                    = module.database.port
  to_port                      = module.database.port
}

# ---------------------------------------------------------------------------
# Presupuesto (decisión 9.11): se crea solo si hay correo de alerta
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "monthly" {
  count        = var.budget_alert_email != "" ? 1 : 0
  name         = "${local.name}-mensual"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
