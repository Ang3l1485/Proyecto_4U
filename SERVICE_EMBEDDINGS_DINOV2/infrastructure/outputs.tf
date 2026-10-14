# ==============================================================
# infrastructure/outputs.tf
# Values printed after `terraform apply` -- useful for the
# deploy script and for manual aws CLI commands.
# ==============================================================

output "ecr_repository_url" {
  description = "Full ECR URI -- use this as the image in the task definition."
  value       = aws_ecr_repository.locations_export.repository_url
}

output "s3_bucket_name" {
  description = "S3 bucket name where CSVs are exported."
  value       = aws_s3_bucket.export.bucket
}

output "s3_bucket_arn" {
  description = "ARN of the S3 export bucket."
  value       = aws_s3_bucket.export.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster name -- pass as CLUSTER to deploy.sh."
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.main.arn
}

output "task_definition_arn" {
  description = "Latest registered ECS task definition ARN."
  value       = aws_ecs_task_definition.locations_export.arn
}

output "task_execution_role_arn" {
  description = "ARN of the ECS task execution role (pulls images, writes logs)."
  value       = aws_iam_role.ecs_task_execution.arn
}

output "task_role_arn" {
  description = "ARN of the task IAM role (RDS IAM auth + S3 writes)."
  value       = aws_iam_role.task_role.arn
}

output "security_group_id" {
  description = "Security group ID -- pass as SECURITY_GROUP_ID to deploy.sh."
  value       = aws_security_group.fargate_task.id
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name -- tail with: aws logs tail <name> --follow"
  value       = aws_cloudwatch_log_group.ecs_task.name
}

output "public_subnet_ids" {
  description = "Public subnet IDs in the resolved VPC -- pick one as SUBNET_ID for deploy.sh."
  value       = data.aws_subnets.public.ids
}

output "resolved_vpc_id" {
  description = "The VPC ID actually used (explicit var.vpc_id, or the account default VPC)."
  value       = local.resolved_vpc_id
}
