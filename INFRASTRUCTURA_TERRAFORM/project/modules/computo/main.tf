# Modulo computo (ARCHITECTURE §3.4, §5.1, §5.4, §5.7, §5.8; INF-1.3): ECR, cluster, Cloud Map, log groups de los
# procesos, roles de ECS (con el permissions boundary de bootstrap), definiciones de tarea (incluida la de validacion,
# §5.11) y los servicios api, worker y embedding en Fargate. Terraform crea los servicios y CI cambia la imagen
# (ADR-INF-09): los servicios ignoran task_definition y desired_count. El autoescalado y el apagado de embedding
# (INF-2.1) están en escalado.tf.

locals {
  repos = {
    backend   = "${var.proyecto}/backend"
    embedding = "${var.proyecto}/embedding"
  }

  procesos = ["api", "worker", "embedding", "migrate", "validacion"]

  # Roles de tarea (§5.8). La tarea de validacion usa el de migrate (sin permisos sobre AWS).
  roles_tarea = ["api", "worker", "embedding", "migrate"]

  # Variables en texto plano (§5.4).
  entorno_base = {
    APP_ENV   = var.entorno
    LOG_LEVEL = "INFO"
  }
  entorno_db = merge(local.entorno_base, {
    AWS_REGION = var.region
    DB_HOST    = var.db_host
    DB_PORT    = tostring(var.db_puerto)
    DB_NAME    = var.db_nombre
    DB_USER    = var.db_usuario
    DB_SSLMODE = "require"
  })
  entorno_backend = merge(local.entorno_db, {
    S3_BUCKET_DATASET = var.bucket_dataset
    SQS_URL_INGESTA   = var.colas["ingesta"].url
    SQS_URL_PURGA     = var.colas["purga"].url
    EMBEDDING_URL     = "http://embedding.${aws_service_discovery_private_dns_namespace.principal.name}:8080"
  })

  # Secretos (§5.4): valueFrom = "<ARN>:<clave>::".
  secreto_db_password = "${var.secretos["db"]}:password::"

  salud = {
    api       = "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3)"
    embedding = "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)"
  }

  # Una entrada por familia de §5.1. Los comandos los fija BACKEND_FASTAPI §5.9 (api usa el CMD de la imagen) y
  # SERVICE_EMBEDDING §5.5 (CMD de la imagen).
  tareas = {
    api = {
      imagen  = "${aws_ecr_repository.repos["backend"].repository_url}:${var.imagen_inicial_tag}"
      cpu     = 256
      memoria = 512
      rol     = "api"
      comando = null
      puerto  = 8000
      salud   = { comando = local.salud["api"], inicio = 30 }
      entorno = local.entorno_backend
      secretos = {
        DB_PASSWORD = local.secreto_db_password
        JWT_SECRET  = "${var.secretos["jwt"]}:secret::"
      }
    }
    worker = {
      imagen   = "${aws_ecr_repository.repos["backend"].repository_url}:${var.imagen_inicial_tag}"
      cpu      = 256
      memoria  = 512
      rol      = "worker"
      comando  = ["python", "-m", "app.worker"]
      puerto   = null
      salud    = null
      entorno  = local.entorno_backend
      secretos = { DB_PASSWORD = local.secreto_db_password }
    }
    embedding = {
      imagen   = "${aws_ecr_repository.repos["embedding"].repository_url}:${var.imagen_inicial_tag}"
      cpu      = 2048
      memoria  = 4096
      rol      = "embedding"
      comando  = null
      puerto   = 8080
      salud    = { comando = local.salud["embedding"], inicio = 180 }
      entorno  = merge(local.entorno_base, { TORCH_NUM_THREADS = "2" })
      secretos = {}
    }
    migrate = {
      imagen  = "${aws_ecr_repository.repos["backend"].repository_url}:${var.imagen_inicial_tag}"
      cpu     = 256
      memoria = 512
      rol     = "migrate"
      comando = ["python", "-m", "app.cli", "migrar"]
      puerto  = null
      salud   = null
      entorno = local.entorno_db
      secretos = {
        DB_PASSWORD            = local.secreto_db_password
        ADMIN_INICIAL_CORREO   = "${var.secretos["admin_inicial"]}:correo::"
        ADMIN_INICIAL_PASSWORD = "${var.secretos["admin_inicial"]}:password::"
      }
    }
    # Tarea de validacion (§5.11): imagen publica con psql y nslookup. Los validadores sobrescriben el comando.
    validacion = {
      imagen  = "public.ecr.aws/docker/library/postgres:17-alpine"
      cpu     = 256
      memoria = 512
      rol     = "migrate"
      comando = ["sh", "-c", "echo 'tarea de validacion: se lanza con run-task sobrescribiendo el comando'"]
      puerto  = null
      salud   = null
      entorno = {
        PGHOST     = var.db_host
        PGPORT     = tostring(var.db_puerto)
        PGDATABASE = var.db_nombre
        PGUSER     = var.db_usuario
      }
      secretos = { PGPASSWORD = local.secreto_db_password }
    }
  }

  # Servicios (§3.4). registro = tipos de registro de Cloud Map; puerto del SRV en api (API Gateway solo lee SRV).
  servicios = {
    api       = { exec = true, registro = true, puerto_srv = 8000 }
    worker    = { exec = false, registro = false, puerto_srv = null }
    embedding = { exec = false, registro = true, puerto_srv = null }
  }

  registros_dns = {
    api       = ["A", "SRV"]
    embedding = ["A"]
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# ECR (§5.1, §5.10): etiquetas inmutables, escaneo basico al subir y conservar las 5 imagenes mas recientes.
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_ecr_repository" "repos" {
  for_each = local.repos

  name                 = each.value
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "repos" {
  for_each = aws_ecr_repository.repos

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conservar las 5 imagenes mas recientes"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------------------------------------------------
# Cluster, Cloud Map y log groups
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_ecs_cluster" "principal" {
  name = var.prefijo

  # Sin Container Insights (§3.8): tiene costo y las alertas no lo necesitan.
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_service_discovery_private_dns_namespace" "principal" {
  name        = "${var.proyecto}.local"
  description = "DNS privado de los servicios de ${var.prefijo}"
  vpc         = var.vpc_id
}

# Sin health_check_custom_config: Cloud Map da por sanas las instancias que ECS registra, y ECS las quita cuando la
# tarea se detiene o deja de estar sana.
resource "aws_service_discovery_service" "servicios" {
  for_each = local.registros_dns

  name = each.key

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.principal.id
    routing_policy = "MULTIVALUE"

    dynamic "dns_records" {
      for_each = each.value
      content {
        type = dns_records.value
        ttl  = 10
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "procesos" {
  for_each = toset(local.procesos)

  name              = "/${var.proyecto}/${var.entorno}/${each.key}"
  retention_in_days = 14
}

# ---------------------------------------------------------------------------------------------------------------------
# IAM (§5.8). Todos los roles llevan el permissions boundary de bootstrap (ADR-INF-12).
# ---------------------------------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "confianza_ecs" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.cuenta_id]
    }
  }
}

resource "aws_iam_role" "ejecucion" {
  name                 = "${var.prefijo}-ecs-ejecucion"
  description          = "Rol de ejecucion comun de ECS: ECR, logs y los tres secretos"
  assume_role_policy   = data.aws_iam_policy_document.confianza_ecs.json
  permissions_boundary = var.limite_roles_arn
}

resource "aws_iam_role_policy_attachment" "ejecucion" {
  role       = aws_iam_role.ejecucion.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ejecucion_secretos" {
  statement {
    sid       = "LeerSecretos"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = values(var.secretos)
  }
}

resource "aws_iam_role_policy" "ejecucion_secretos" {
  name   = "secretos"
  role   = aws_iam_role.ejecucion.id
  policy = data.aws_iam_policy_document.ejecucion_secretos.json
}

resource "aws_iam_role" "tareas" {
  for_each = toset(local.roles_tarea)

  name                 = "${var.prefijo}-tarea-${each.key}"
  description          = "Rol de tarea de ${each.key} (ARCHITECTURE 5.8)"
  assume_role_policy   = data.aws_iam_policy_document.confianza_ecs.json
  permissions_boundary = var.limite_roles_arn
}

locals {
  objetos_app = [for p in ["dataset", "thumbs", "lugares"] : "${var.bucket_dataset_arn}/${p}/*"]
  colas_app   = [var.colas["ingesta"].arn, var.colas["purga"].arn]
}

data "aws_iam_policy_document" "tarea_api" {
  statement {
    sid       = "FirmarUrls"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = local.objetos_app
  }

  statement {
    sid       = "Encolar"
    actions   = ["sqs:SendMessage"]
    resources = local.colas_app
  }

  statement {
    sid = "EcsExec"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "tarea_worker" {
  statement {
    sid       = "Objetos"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = local.objetos_app
  }

  statement {
    sid       = "ListarParaPurgar"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_dataset_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["dataset/*", "thumbs/*"]
    }
  }

  statement {
    sid = "Consumir"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = local.colas_app
  }
}

resource "aws_iam_role_policy" "tarea_api" {
  name   = "tarea"
  role   = aws_iam_role.tareas["api"].id
  policy = data.aws_iam_policy_document.tarea_api.json
}

resource "aws_iam_role_policy" "tarea_worker" {
  name   = "tarea"
  role   = aws_iam_role.tareas["worker"].id
  policy = data.aws_iam_policy_document.tarea_worker.json
}

# ---------------------------------------------------------------------------------------------------------------------
# Definiciones de tarea (§3.4, §5.1, §5.4, §5.7). Un solo contenedor, app, por tarea. Las claves que no aplican se
# omiten (en vez de null o []) para que ECS devuelva lo mismo que se envio y el plan quede vacio.
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "tareas" {
  for_each = local.tareas

  family                   = "${var.prefijo}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memoria
  execution_role_arn       = aws_iam_role.ejecucion.arn
  task_role_arn            = aws_iam_role.tareas[each.value.rol].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([merge(
    {
      name        = "app"
      image       = each.value.imagen
      essential   = true
      environment = [for k in sort(keys(each.value.entorno)) : { name = k, value = each.value.entorno[k] }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.procesos[each.key].name
          awslogs-region        = var.region
          awslogs-stream-prefix = each.key
        }
      }
    },
    each.value.comando == null ? {} : { command = each.value.comando },
    length(each.value.secretos) == 0 ? {} : {
      secrets = [for k in sort(keys(each.value.secretos)) : { name = k, valueFrom = each.value.secretos[k] }]
    },
    each.value.puerto == null ? {} : {
      portMappings = [{ containerPort = each.value.puerto, hostPort = each.value.puerto, protocol = "tcp" }]
    },
    each.value.salud == null ? {} : {
      healthCheck = {
        command     = ["CMD", "python", "-c", each.value.salud.comando]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = each.value.salud.inicio
      }
    },
  )])
}

# ---------------------------------------------------------------------------------------------------------------------
# Servicios (§3.4): desired_count = 0 hasta el primer despliegue (§5.9); circuit breaker con rollback.
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_ecs_service" "servicios" {
  for_each = local.servicios

  name                          = each.key
  cluster                       = aws_ecs_cluster.principal.id
  task_definition               = aws_ecs_task_definition.tareas[each.key].arn
  desired_count                 = 0
  launch_type                   = "FARGATE"
  platform_version              = "LATEST"
  enable_execute_command        = each.value.exec
  availability_zone_rebalancing = "DISABLED" # una sola zona (ADR-INF-03)

  network_configuration {
    subnets          = [var.subred_tareas]
    security_groups  = [var.grupos_seguridad[each.key]]
    assign_public_ip = true # sin NAT (ADR-INF-02)
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  dynamic "service_registries" {
    for_each = each.value.registro ? [1] : []
    content {
      registry_arn   = aws_service_discovery_service.servicios[each.key].arn
      container_name = each.value.puerto_srv == null ? null : "app"
      container_port = each.value.puerto_srv
    }
  }

  # CI registra revisiones nuevas y fija las replicas (ADR-INF-09); worker y embedding los escala escalado.tf.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
