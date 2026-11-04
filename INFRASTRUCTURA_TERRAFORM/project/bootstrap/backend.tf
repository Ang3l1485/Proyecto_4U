# Estado de bootstrap en el bucket que crea este mismo módulo (ARCHITECTURE §3.9, §5.1).
#
# La primera vez el bucket todavía no existe: se aplica con estado local usando un backend_override.tf (ignorado
# por Git) y luego se migra con «terraform init -migrate-state». Pasos en README.md.
#
# Un bloque backend no admite variables: los valores repiten los de terraform.tfvars a propósito.

terraform {
  backend "s3" {
    bucket       = "campus-locator-tfstate-648617469176"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
