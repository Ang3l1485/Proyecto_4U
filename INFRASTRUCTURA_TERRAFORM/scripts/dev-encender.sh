#!/usr/bin/env bash
# Enciende dev. Si RDS estaba detenida, la arranca y espera a que esté disponible.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
BD="campus-locator-dev-db"

ESTADO="$(aws rds describe-db-instances --db-instance-identifier "$BD" \
  --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo desconocido)"

if [[ "$ESTADO" == "stopped" ]]; then
  aws rds start-db-instance --db-instance-identifier "$BD" >/dev/null
  echo "Arrancando RDS (tarda unos minutos)..."
fi
if [[ "$ESTADO" == "stopped" || "$ESTADO" == "starting" ]]; then
  aws rds wait db-instance-available --db-instance-identifier "$BD"
fi

terraform -chdir="$RAIZ/envs/dev" apply -auto-approve -var encendido=true

echo "Dev encendido. El embedding tarda en cargar el modelo antes de pasar el health check."
terraform -chdir="$RAIZ/envs/dev" output api_base_url
