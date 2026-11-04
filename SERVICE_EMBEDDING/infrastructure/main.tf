# ==============================================================
# infrastructure/main.tf
# ==============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

locals {
  resolved_vpc_id = var.vpc_id != null ? var.vpc_id : data.aws_vpc.default.id
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [local.resolved_vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

# ==============================================================
# ECR
# ==============================================================

resource "aws_ecr_repository" "locations_export" {
  name                 = "locations-export"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "locations_export" {
  repository = aws_ecr_repository.locations_export.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# ==============================================================
# S3 (legacy bucket kept)
# ==============================================================

resource "aws_s3_bucket" "export" {
  bucket = var.s3_bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "export" {
  bucket                  = aws_s3_bucket.export.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "export" {
  bucket = aws_s3_bucket.export.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "export" {
  bucket = aws_s3_bucket.export.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ==============================================================
# IAM
# ==============================================================

data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
  tags               = var.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task_role" {
  name               = "locations-export-task-role"
  description        = "CLIP similarity API: RDS IAM auth + S3"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
  tags               = var.tags
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "task_role_policy" {
  statement {
    sid     = "AllowRDSIAMAuth"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:*/${var.db_user}"
    ]
  }
  statement {
    sid     = "AllowS3ListInput"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.input_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.input_prefix}*", "${var.output_prefix}*"]
    }
  }
  statement {
    sid     = "AllowS3ReadInput"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.input_bucket}/${var.input_prefix}*"]
  }
  statement {
    sid    = "AllowS3WriteOutput"
    effect = "Allow"
    actions = ["s3:PutObject", "s3:PutObjectAcl"]
    resources = ["arn:aws:s3:::${var.output_bucket}/${var.output_prefix}*"]
  }
  statement {
    sid    = "AllowS3ExportLegacy"
    effect = "Allow"
    actions = ["s3:PutObject", "s3:PutObjectAcl"]
    resources = ["${aws_s3_bucket.export.arn}/${var.s3_key_prefix}*"]
  }
}

resource "aws_iam_role_policy" "task_role_inline" {
  name   = "locations-export-policy"
  role   = aws_iam_role.task_role.id
  policy = data.aws_iam_policy_document.task_role_policy.json
}

# ==============================================================
# CloudWatch Logs
# ==============================================================

resource "aws_cloudwatch_log_group" "ecs_task" {
  name              = "/ecs/locations-info-export"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# ==============================================================
# ECS Cluster
# ==============================================================

resource "aws_ecs_cluster" "main" {
  name = var.cluster_name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = var.tags
}

# ==============================================================
# ECS Task Definition (FastAPI on port 8080)
# ==============================================================

resource "aws_ecs_task_definition" "locations_export" {
  family                   = "locations-info-export"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "2048"
  memory                   = "4096"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.task_role.arn

  container_definitions = jsonencode([{
    name      = "locations-export"
    image     = "${aws_ecr_repository.locations_export.repository_url}:latest"
    essential = true

    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]

    environment = [
      { name = "DB_HOST",          value = var.db_host },
      { name = "DB_PORT",          value = tostring(var.db_port) },
      { name = "DB_USER",          value = var.db_user },
      { name = "DB_NAME",          value = var.db_name },
      { name = "DB_REGION",        value = var.aws_region },
      { name = "EMBEDDINGS_TABLE", value = var.embeddings_table },
      { name = "LOCATIONS_TABLE",  value = var.locations_table },
      { name = "INPUT_BUCKET",     value = var.input_bucket },
      { name = "INPUT_PREFIX",     value = var.input_prefix },
      { name = "OUTPUT_BUCKET",    value = var.output_bucket },
      { name = "OUTPUT_PREFIX",    value = var.output_prefix },
      { name = "CLIP_MODEL_ID",    value = var.clip_model_id },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs_task.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = var.tags
}

# ==============================================================
# Security Group
# ==============================================================

resource "aws_security_group" "fargate_task" {
  name        = "locations-export-sg"
  description = "FastAPI on 8080 plus outbound to RDS and AWS APIs"
  vpc_id      = local.resolved_vpc_id

  ingress {
    description = "FastAPI from internet"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "PostgreSQL to RDS"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "HTTPS to AWS APIs and HuggingFace"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "locations-export-sg" })
}

# ==============================================================
# ECS Service (always 1 task running, scaled to 0 to save cost)
# ==============================================================

resource "aws_ecs_service" "api" {
  name            = "locations-export-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.locations_export.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.fargate_task.id]
    assign_public_ip = true
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  tags = var.tags
}