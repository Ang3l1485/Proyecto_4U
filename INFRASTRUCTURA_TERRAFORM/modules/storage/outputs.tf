output "dataset_bucket" {
  value = aws_s3_bucket.this["dataset"].bucket
}

output "dataset_bucket_arn" {
  value = aws_s3_bucket.this["dataset"].arn
}

output "scans_bucket" {
  description = "Vacío si no se creó el bucket de escaneos"
  value       = var.create_scans_bucket ? aws_s3_bucket.this["scans"].bucket : ""
}

output "scans_bucket_arn" {
  value = var.create_scans_bucket ? aws_s3_bucket.this["scans"].arn : ""
}

output "bucket_arns" {
  description = "ARNs de todos los buckets creados"
  value       = [for b in aws_s3_bucket.this : b.arn]
}
