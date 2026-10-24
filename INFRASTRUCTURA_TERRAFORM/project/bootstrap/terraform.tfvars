# Valores de dev para bootstrap (ARCHITECTURE §5.3). Se versiona: no contiene secretos.

aws_account_id  = "648617469176"
region          = "us-east-1"
proyecto        = "campus-locator"
entorno         = "dev"
presupuesto_usd = 100

# Decididos el 2026-10-23 (PLAN INF-0.1, «Requiere decidir antes»). El repositorio es público.
github_repo    = "AlejandroSPosada/4U_project"
correo_alertas = "franklinalejo1042005@gmail.com"

# El repositorio se creó el 2026-09-09, después del 2026-07-15: GitHub emite el sub inmutable
# repo:AlejandroSPosada@142058005/4U_project@1362957467:… (README.md, «Formato del sub»).
# Origen: gh api repos/AlejandroSPosada/4U_project --jq "{propietario: .owner.id, repositorio: .id}"
github_ids = { propietario = 142058005, repositorio = 1362957467 }
