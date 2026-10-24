# Estado remoto de envs/dev (ARCHITECTURE §3.9, ADR-INF-08). El bucket lo crea bootstrap (INF-0.1).
# Bloqueo nativo de S3 (Terraform >= 1.10): el bloqueo es el objeto dev/terraform.tfstate.tflock del mismo bucket,
# sin tabla de DynamoDB. allowed_account_ids hace que init falle con credenciales de otra cuenta.
terraform {
  backend "s3" {
    bucket              = "campus-locator-tfstate-648617469176"
    key                 = "dev/terraform.tfstate"
    region              = "us-east-1"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["648617469176"]
  }
}
