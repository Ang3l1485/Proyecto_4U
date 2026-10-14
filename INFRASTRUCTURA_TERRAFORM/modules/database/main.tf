resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.subnet_ids
}

# El security group no trae reglas de entrada: el ensamblado del ambiente agrega
# la del security group del backend (evita una dependencia circular con ecs_service).
resource "aws_security_group" "this" {
  name        = "${var.name}-db"
  description = "PostgreSQL de Campus Locator: solo accesible desde el backend"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-db" }
}

# pgvector se habilita con CREATE EXTENSION vector (no requiere shared_preload_libraries).
resource "aws_db_parameter_group" "this" {
  name        = "${var.name}-pg"
  family      = "postgres${var.engine_major_version}"
  description = "Parametros de Campus Locator"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "this" {
  identifier = "${var.name}-db"

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.master_username
  # La contraseña la genera y rota AWS en Secrets Manager: no pasa por Terraform ni por el state.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period = var.backup_retention_days
  copy_tags_to_snapshot   = true

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${var.name}-db-final" : null

  auto_minor_version_upgrade = true
  apply_immediately          = !var.deletion_protection

  performance_insights_enabled = false
}
