# INF-0.1 — Bootstrap de la cuenta (PLAN §2.3, ARCHITECTURE §3.9 y §4).
# Terraform ≥ 1.10 por el bloqueo nativo en S3 (use_lockfile, ADR-INF-08).

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
