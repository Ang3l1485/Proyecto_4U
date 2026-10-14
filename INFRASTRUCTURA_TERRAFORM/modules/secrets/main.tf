terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# Clave con la que el backend firma los JWT. Se genera aquí y nunca se escribe en tfvars.
# Nota: el valor queda en el state (cifrado, acceso restringido; ver ARCHITECTURE sección 5).
resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt" {
  name                    = "${var.name}/jwt-secret"
  description             = "Clave de firma de los JWT de Campus Locator"
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}
