# Módulo red (INF-1.1): VPC, subredes, Internet Gateway, rutas, endpoint de S3 y grupos de seguridad.
# Contratos: docs/ARCHITECTURE.md §3.2 (red), §5.1 (nombres) y §5.7 (grupos y puertos).
# Las cuatro etiquetas de §5.1 las pone el proveedor (default_tags); aquí solo se añade Name.

locals {
  # Las cuatro /24 de §5.1 salen de la /16 de la VPC: 0 y 1 públicas, 10 y 11 privadas.
  subredes = {
    "publica-a" = { cidr = cidrsubnet(var.cidr_vpc, 8, 0), zona = var.az_computo, publica = true }
    "publica-b" = { cidr = cidrsubnet(var.cidr_vpc, 8, 1), zona = var.az_secundaria, publica = true }
    "privada-a" = { cidr = cidrsubnet(var.cidr_vpc, 8, 10), zona = var.az_computo, publica = false }
    "privada-b" = { cidr = cidrsubnet(var.cidr_vpc, 8, 11), zona = var.az_secundaria, publica = false }
  }

  # Grupos de §5.7. La descripción de un grupo no se puede cambiar sin recrearlo (y recrearlo arrastra
  # todo lo que lo usa): es genérica a propósito y solo admite ASCII (sin tildes).
  grupos = {
    vpclink   = "VPC Link de API Gateway"
    api       = "Tareas api, migrate y validacion"
    worker    = "Tareas worker"
    embedding = "Tareas embedding"
    rds       = "Instancia RDS PostgreSQL"
  }

  # Reglas entrantes de §5.7: solo desde otros grupos, nunca desde un CIDR.
  entradas = {
    "api-desde-vpclink"      = { grupo = "api", puerto = 8000, origen = "vpclink" }
    "embedding-desde-api"    = { grupo = "embedding", puerto = 8080, origen = "api" }
    "embedding-desde-worker" = { grupo = "embedding", puerto = 8080, origen = "worker" }
    "rds-desde-api"          = { grupo = "rds", puerto = 5432, origen = "api" }
    "rds-desde-worker"       = { grupo = "rds", puerto = 5432, origen = "worker" }
  }

  # Grupos con salida libre (internet por el IGW: ECR, S3, SQS, Secrets Manager, CloudWatch; sin NAT, ADR-INF-02).
  # vpclink solo sale hacia api y rds no tiene salida.
  salida_libre = ["api", "worker", "embedding"]
}

resource "aws_vpc" "principal" {
  cidr_block           = var.cidr_vpc
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.prefijo}-vpc" }
}

# Al adoptarlo, Terraform le quita todas las reglas: nada debe usar el grupo default (§5.7).
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = "${var.prefijo}-default" }
}

resource "aws_internet_gateway" "principal" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = "${var.prefijo}-igw" }
}

resource "aws_subnet" "subredes" {
  for_each = local.subredes

  vpc_id            = aws_vpc.principal.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.zona

  tags = { Name = "${var.prefijo}-${each.key}" }
}

# Rutas: sin bloques route en línea (las rutas van en aws_route y la del endpoint de S3 la gestiona AWS).
resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = "${var.prefijo}-publica" }
}

resource "aws_route" "publica_internet" {
  route_table_id         = aws_route_table.publica.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.principal.id
}

# Solo la ruta local: RDS no tiene salida a internet.
resource "aws_route_table" "privada" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = "${var.prefijo}-privada" }
}

resource "aws_route_table_association" "subredes" {
  for_each = local.subredes

  subnet_id      = aws_subnet.subredes[each.key].id
  route_table_id = each.value.publica ? aws_route_table.publica.id : aws_route_table.privada.id
}

# Gateway endpoint (gratuito) en la tabla pública: las tareas llegan a S3 sin salir a internet.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.principal.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.publica.id]

  tags = { Name = "${var.prefijo}-s3" }
}

# Grupos sin reglas en línea: cada regla es un recurso propio, así las referencias cruzadas no forman ciclos.
resource "aws_security_group" "grupos" {
  for_each = local.grupos

  name        = "${var.prefijo}-${each.key}"
  description = "${var.prefijo}: ${each.value}"
  vpc_id      = aws_vpc.principal.id

  tags = { Name = "${var.prefijo}-${each.key}" }
}

resource "aws_vpc_security_group_ingress_rule" "entradas" {
  for_each = local.entradas

  security_group_id            = aws_security_group.grupos[each.value.grupo].id
  referenced_security_group_id = aws_security_group.grupos[each.value.origen].id
  ip_protocol                  = "tcp"
  from_port                    = each.value.puerto
  to_port                      = each.value.puerto
  description                  = "${each.value.puerto}/tcp desde ${var.prefijo}-${each.value.origen}"
}

resource "aws_vpc_security_group_egress_rule" "vpclink_a_api" {
  security_group_id            = aws_security_group.grupos["vpclink"].id
  referenced_security_group_id = aws_security_group.grupos["api"].id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  description                  = "8000/tcp hacia ${var.prefijo}-api"
}

resource "aws_vpc_security_group_egress_rule" "salida_libre" {
  for_each = toset(local.salida_libre)

  security_group_id = aws_security_group.grupos[each.key].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Todo hacia internet por el IGW"
}
