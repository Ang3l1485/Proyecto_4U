# Secretos de ARCHITECTURE §3.6 y §5.4. Los valores los genera Terraform y quedan en el estado (ADR-INF-07, R5).

# Contraseña de la base: solo letras y dígitos, para que ningún consumidor tenga que escaparla (URL de conexión,
# shell). 40 caracteres de 62 símbolos ≈ 238 bits.
resource "random_password" "db" {
  length  = 40
  special = false
}

# Clave HMAC del JWT: 64 bytes aleatorios; el secreto guarda su base64 y el backend usa esa cadena tal cual.
resource "random_bytes" "jwt" {
  length = 64
}

# Contraseña del administrador inicial: se consulta en la consola para el primer inicio de sesión y se cambia después.
resource "random_password" "admin_inicial" {
  length      = 24
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

locals {
  # clave del mapa de salidas => sufijo del nombre del secreto
  secretos = {
    db            = { sufijo = "db", descripcion = "Conexion a RDS: host, port, dbname, username, password" }
    jwt           = { sufijo = "jwt", descripcion = "Clave HMAC del JWT del backend (64 bytes en base64)" }
    admin_inicial = { sufijo = "admin-inicial", descripcion = "Correo y contrasena del administrador inicial" }
  }
}

resource "aws_secretsmanager_secret" "secretos" {
  for_each = local.secretos

  name        = "${var.ruta}/${each.value.sufijo}"
  description = each.value.descripcion
  # Borrado recuperable durante 7 días (el mínimo); mientras tanto el nombre no se puede volver a crear.
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.secretos["db"].id
  secret_string = jsonencode({
    host     = var.db_host
    port     = var.db_puerto
    dbname   = var.db_nombre
    username = var.db_usuario
    password = random_password.db.result
  })
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id = aws_secretsmanager_secret.secretos["jwt"].id
  secret_string = jsonencode({
    secret = random_bytes.jwt.base64
  })
}

resource "aws_secretsmanager_secret_version" "admin_inicial" {
  secret_id = aws_secretsmanager_secret.secretos["admin_inicial"].id
  secret_string = jsonencode({
    correo   = var.admin_inicial_correo
    password = random_password.admin_inicial.result
  })
}
