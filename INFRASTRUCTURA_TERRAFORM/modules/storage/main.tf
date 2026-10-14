locals {
  # El filtro `if` evita el conflicto de tipos de un condicional entre objetos distintos.
  buckets = merge(
    { dataset = { name = "${var.name}-dataset-${var.account_id}" } },
    { for k, v in { scans = { name = "${var.name}-scans-${var.account_id}" } } : k => v if var.create_scans_bucket }
  )
}

resource "aws_s3_bucket" "this" {
  for_each      = local.buckets
  bucket        = each.value.name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "tls" {
  for_each = aws_s3_bucket.this

  statement {
    sid       = "SoloTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]

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

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  policy   = data.aws_iam_policy_document.tls[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

# Solo el bucket de escaneos expira (privacidad, decisión 9.6).
resource "aws_s3_bucket_lifecycle_configuration" "scans" {
  count  = var.create_scans_bucket ? 1 : 0
  bucket = aws_s3_bucket.this["scans"].id

  rule {
    id     = "expirar-escaneos"
    status = "Enabled"
    filter {}

    expiration {
      days = var.scans_expire_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Limpia subidas multiparte abandonadas en el dataset.
resource "aws_s3_bucket_lifecycle_configuration" "dataset" {
  bucket = aws_s3_bucket.this["dataset"].id

  rule {
    id     = "limpiar-multiparte"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
