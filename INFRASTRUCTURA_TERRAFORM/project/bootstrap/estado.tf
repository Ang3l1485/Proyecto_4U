# Bucket del estado remoto de Terraform (ARCHITECTURE §3.9, §5.1): versionado, cifrado y privado.
# Claves: bootstrap/terraform.tfstate y dev/terraform.tfstate (+ dev/terraform.tfstate.tflock, bloqueo nativo).

resource "aws_s3_bucket" "estado" {
  bucket = "${var.proyecto}-tfstate-${var.aws_account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "estado" {
  bucket = aws_s3_bucket.estado.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "estado" {
  bucket = aws_s3_bucket.estado.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Cada plan crea y borra el .tflock: sin esta regla se acumularían versiones antiguas y marcas de borrado.
# Se conservan siempre las 10 versiones anteriores más recientes de cada estado, y el resto durante 90 días.
resource "aws_s3_bucket_lifecycle_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    id     = "versiones-antiguas"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 10
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.estado]
}

data "aws_iam_policy_document" "estado_solo_tls" {
  statement {
    sid       = "SoloTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.estado.arn, "${aws_s3_bucket.estado.arn}/*"]

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

resource "aws_s3_bucket_policy" "estado" {
  bucket = aws_s3_bucket.estado.id
  policy = data.aws_iam_policy_document.estado_solo_tls.json

  depends_on = [aws_s3_bucket_public_access_block.estado]
}
