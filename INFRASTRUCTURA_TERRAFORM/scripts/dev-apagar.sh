#!/usr/bin/env bash
# Apaga dev: backend y embedding a 0 tareas (deja de cobrar Fargate).
# Uso:  scripts/dev-apagar.sh            -> solo ECS
#       scripts/dev-apagar.sh --con-bd   -> también detiene RDS (AWS la reinicia sola a los 7 días)
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
terraform -chdir="$RAIZ/envs/dev" apply -auto-approve -var encendido=false

if [[ "${1:-}" == "--con-bd" ]]; then
  # Identificador = <project>-<env>-db (ver modules/database)
  aws rds stop-db-instance --db-instance-identifier campus-locator-dev-db >/dev/null
  echo "RDS detenida (se reinicia sola en 7 días si no la enciendes antes)."
fi

echo "Dev apagado. El ALB, RDS (si no la detuviste), S3 y ECR siguen existiendo y cobrando un mínimo."
