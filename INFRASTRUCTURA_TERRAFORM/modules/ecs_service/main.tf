data "aws_region" "current" {}

locals {
  full_name = "${var.name}-${var.service_name}"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.full_name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# IAM: rol de ejecución (tirar imágenes y escribir logs) y rol de tarea (permisos de la app)
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.full_name}-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${local.full_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# Un servicio sin permisos de AWS (embedding) deja attach_task_policy = false.
resource "aws_iam_role_policy" "task" {
  count  = var.attach_task_policy ? 1 : 0
  name   = "${local.full_name}-task"
  role   = aws_iam_role.task.id
  policy = var.task_policy_json
}

# ---------------------------------------------------------------------------
# Security group
# ---------------------------------------------------------------------------
resource "aws_security_group" "this" {
  name        = local.full_name
  description = "Servicio ${var.service_name}: solo acepta trafico de los SG indicados"
  vpc_id      = var.vpc_id

  tags = { Name = local.full_name }
}

resource "aws_vpc_security_group_ingress_rule" "from_sg" {
  count                        = length(var.ingress_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = var.ingress_security_group_ids[count.index]
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
}

# Salida abierta: ECR, S3, Secrets Manager, CloudWatch (y RDS / embedding para el backend).
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ---------------------------------------------------------------------------
# Tarea y servicio
# ---------------------------------------------------------------------------
resource "aws_ecs_task_definition" "this" {
  family                   = local.full_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([{
    name      = var.service_name
    image     = var.image
    essential = true

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    environment = [for k, v in var.environment : { name = k, value = v }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = var.service_name
      }
    }
  }])
}

resource "aws_service_discovery_service" "this" {
  count = var.enable_service_discovery ? 1 : 0
  name  = var.service_name

  dns_config {
    namespace_id   = var.service_discovery_namespace_id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_ecs_service" "this" {
  name            = var.service_name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Deja que un despliegue fallido se revierta solo.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = var.target_group_arn != null ? var.health_check_grace_seconds : null

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.this.id]
    assign_public_ip = var.assign_public_ip
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn != null ? [1] : []

    content {
      target_group_arn = var.target_group_arn
      container_name   = var.service_name
      container_port   = var.container_port
    }
  }

  dynamic "service_registries" {
    for_each = aws_service_discovery_service.this

    content {
      registry_arn = service_registries.value.arn
    }
  }

  # CI registra nuevas definiciones de tarea con la etiqueta del commit (ARCHITECTURE sección 7):
  # Terraform no debe revertir esos despliegues.
  lifecycle {
    ignore_changes = [task_definition]
  }
}
