output "security_group_id" {
  value = aws_security_group.this.id
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
