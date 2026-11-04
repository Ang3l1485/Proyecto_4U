# Valores de dev (ARCHITECTURE §5.3). Se versiona: no contiene secretos.
aws_account_id = "648617469176"
region         = "us-east-1"
proyecto       = "campus-locator"
entorno        = "dev"

# INF-1.1 (red)
cidr_vpc      = "10.20.0.0/16"
az_computo    = "us-east-1a"
az_secundaria = "us-east-1b"

# INF-1.2
rds_clase  = "db.t4g.micro"
rds_gb     = 20
rds_gb_max = 50
pg_version = "17"

# INF-1.3
imagen_inicial_tag = "bootstrap"

# INF-2.1 (noche = null quita el apagado nocturno)
apagado_embedding = {
  zona            = "America/Bogota"
  noche           = "cron(0 22 * * ? *)"
  inactividad_min = 45
}

# INF-3.1: el mismo de bootstrap/terraform.tfvars (presupuesto). SNS envía un correo de confirmación tras el apply.
correo_alertas = "franklinalejo1042005@gmail.com"
