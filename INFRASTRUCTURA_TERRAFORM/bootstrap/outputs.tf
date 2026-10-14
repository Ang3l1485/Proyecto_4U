output "state_bucket" {
  description = "Bucket para usar en envs/*/backend.tf"
  value       = aws_s3_bucket.state.bucket
}

output "github_ci_role_arn" {
  description = "ARN del rol que asumen los workflows de GitHub Actions"
  value       = aws_iam_role.github_ci.arn
}
