# Datos de ARCHITECTURE §3.5, §5.5 y §5.6: RDS PostgreSQL, bucket del dataset y colas SQS con la notificación
# S3 → SQS. Las reglas de red de RDS viven en el módulo red (§5.7): aquí solo se usa el grupo -rds.

locals {
  base    = "campus_locator"
  usuario = "campus_app"

  colas = {
    ingesta = { visibilidad = 180 }
    purga   = { visibilidad = 300 }
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_db_subnet_group" "principal" {
  name        = "${var.prefijo}-db"
  description = "Subredes privadas de RDS; la segunda zona solo porque RDS exige dos (ADR-INF-03)"
  subnet_ids  = var.subredes_privadas
}

resource "aws_db_parameter_group" "principal" {
  name        = "${var.prefijo}-pg${var.pg_version}"
  family      = "postgres${var.pg_version}"
  description = "Parametros de ${var.prefijo}-db: TLS obligatorio"

  # En PostgreSQL 17, 1 ya es el valor por defecto: RDS lo lista como Source = system con ApplyMethod = pending-reboot,
  # y el proveedor lo lee así. Con "immediate" (el valor por defecto del proveedor) el plan nunca quedaría vacío. El
  # método no cambia nada: el valor efectivo es 1 en los dos casos.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  # Si cambia la versión mayor cambian el nombre y la familia, y el grupo nuevo debe existir antes de que la instancia
  # deje el viejo. No cambiar la descripción sin cambiar el nombre: RDS recrea el grupo y los dos chocarían por nombre.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "principal" {
  identifier     = "${var.prefijo}-db"
  engine         = "postgres"
  engine_version = var.pg_version # solo la mayor: RDS elige la menor por defecto (≥ 17.1) y la sube sola
  instance_class = var.rds_clase

  allocated_storage     = var.rds_gb
  max_allocated_storage = var.rds_gb_max
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = local.base
  username = local.usuario
  password = var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.principal.name
  vpc_security_group_ids = [var.sg_rds]
  availability_zone      = var.az_computo
  multi_az               = false
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.principal.name

  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false
  apply_immediately           = true # dev: los cambios no esperan a la ventana de mantenimiento

  # Ventanas de madrugada en Bogota (copias 02:00, mantenimiento domingo 03:00; §5.10).
  backup_retention_period = 7
  backup_window           = "07:00-07:30"
  maintenance_window      = "sun:08:00-sun:09:00"
  copy_tags_to_snapshot   = true

  # Si ya existe un snapshot con este nombre (de una destrucción anterior), hay que borrarlo antes de destruir.
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.prefijo}-db-final"
  deletion_protection       = true
}

# ---------------------------------------------------------------------------------------------------------------------
# Bucket del dataset
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "dataset" {
  bucket = "${var.prefijo}-dataset-${var.cuenta_id}"
}

resource "aws_s3_bucket_ownership_controls" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  rule {
    id     = "abortar-subidas-multiparte"
    status = "Enabled"

    filter {} # todo el bucket

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "dataset" {
  statement {
    sid       = "SoloTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.dataset.arn, "${aws_s3_bucket.dataset.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "dataset" {
  bucket = aws_s3_bucket.dataset.id
  policy = data.aws_iam_policy_document.dataset.json

  # S3 rechaza cambios simultáneos de configuración del mismo bucket.
  depends_on = [aws_s3_bucket_public_access_block.dataset]
}

# S3 valida el destino al guardar la notificación: la política de la cola debe existir antes (§4, INF-1.2).
# Al guardarla, S3 envía un s3:TestEvent a la cola.
resource "aws_s3_bucket_notification" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  queue {
    id            = "ingesta-dataset-jpg"
    queue_arn     = aws_sqs_queue.colas["ingesta"].arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "dataset/"
    filter_suffix = ".jpg"
  }

  depends_on = [aws_sqs_queue_policy.ingesta, aws_s3_bucket_policy.dataset]
}

# ---------------------------------------------------------------------------------------------------------------------
# Colas
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = local.colas

  name                      = "${var.prefijo}-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14 días
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "colas" {
  for_each = local.colas

  name                       = "${var.prefijo}-${each.key}"
  visibility_timeout_seconds = each.value.visibilidad
  message_retention_seconds  = 345600 # 4 días
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "ingesta" {
  statement {
    sid       = "EventosDelBucketDataset"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.colas["ingesta"].arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.dataset.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.cuenta_id]
    }
  }
}

resource "aws_sqs_queue_policy" "ingesta" {
  queue_url = aws_sqs_queue.colas["ingesta"].id
  policy    = data.aws_iam_policy_document.ingesta.json
}
