resource "aws_ecs_cluster" "this" {
  name = "${var.name}-cluster"

  setting {
    name  = "containerInsights"
    value = var.container_insights ? "enabled" : "disabled"
  }
}

# Nombres internos: embedding.<namespace> resuelve a las IPs privadas de sus tareas.
resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = var.namespace
  description = "Nombres internos de ${var.name}"
  vpc         = var.vpc_id
}
