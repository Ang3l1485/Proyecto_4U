# Valores de dev. Sin secretos.
env    = "dev"
region = "us-east-1"

enable_nat_gateway = false # decisión 9.7: sin NAT en dev

# Interruptor: terraform apply -var encendido=false  (o usa scripts/dev-apagar.sh)
encendido = true

backend_desired_count   = 1
embedding_desired_count = 1

# Embedding "medio": DINOv2 base en 2 vCPU / 4 GB
embedding_model_name = "dinov2_vitb14"
embedding_cpu        = 2048
embedding_memory     = 4096

db_instance_class        = "db.t4g.micro"
db_multi_az              = false
db_backup_retention_days = 7
db_deletion_protection   = false

log_retention_days = 7

monthly_budget_usd = 40
# budget_alert_email = "tu-correo@ejemplo.com"   # descomentar para crear la alarma de AWS Budgets

# certificate_arn = "arn:aws:acm:us-east-1:...:certificate/..."   # fase 4
