# Validación 0-1 — INF-0.1 Bootstrap de la cuenta

| Campo | Valor |
|---|---|
| Lote | `INF-0.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate01.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P2 y P3 son credenciales: código 3,
según §5.11).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Repositorio de GitHub creado (columna «Para validar» de `PLAN.md` §2.2) | `gh repo view --json nameWithOwner,defaultBranchRef` desde la copia local devuelve el repositorio con rama por defecto `main`; ese `nameWithOwner` es el `<github_repo>` de las demás comprobaciones |
| P2 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |
| P3 | `gh` autenticado con permiso para crear ramas, PR y workflows | `gh auth status` termina con 0 y muestra los *scopes* `repo` y `workflow` |
| P4 | `bootstrap` aplicado, con sus outputs | `terraform -chdir=bootstrap output -json` contiene `rol_gha_terraform_plan_arn`, `rol_gha_terraform_arn`, `rol_gha_deploy_arn`, `bucket_estado` = `campus-locator-tfstate-648617469176` y `github_repo` igual al `nameWithOwner` de P1 |
| P5 | Variables del repositorio que usa el workflow de prueba | `gh variable list --json name,value` contiene `AWS_REGION` = `us-east-1` y `AWS_ROL_TERRAFORM_PLAN_ARN`, `AWS_ROL_TERRAFORM_ARN`, `AWS_ROL_DEPLOY_ARN` iguales a los outputs de P4 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | `s3api head-object` de `bootstrap/terraform.tfstate` en `campus-locator-tfstate-648617469176`; lee el objeto en memoria con `s3api get-object` (sin imprimirlo) y lo compara con `terraform -chdir=bootstrap state pull`; `s3api get-bucket-versioning`, `get-bucket-encryption` y `list-object-versions --prefix bootstrap/terraform.tfstate` | El objeto existe; su `lineage` y `serial` coinciden con los de `state pull` (el estado activo es el remoto); `Status = Enabled`; hay regla de cifrado por defecto (`AES256` o `aws:kms`) y el objeto tiene `ServerSideEncryption`; hay al menos una versión |
| C2 | Crea por la API de GitHub (sin tocar la copia local) la rama `validacion-0-1-<AAAAMMDD-HHMMSS>` desde `main` con `.github/workflows/validacion-0-1.yml` (`on: pull_request`, `permissions: id-token: write`) y abre un PR desde ella. Su job `plan` asume `vars.AWS_ROL_TERRAFORM_PLAN_ARN` con `aws-actions/configure-aws-credentials` y ejecuta `aws sts get-caller-identity`. El script espera consultando la ejecución por la API y lee el log de cada job con `gh api repos/<github_repo>/actions/jobs/<id>/logs` (o `gh run view --log --job <id>`). El primer paso del job imprime el *claim* `sub` del token, nunca el token, para diagnosticar su formato (ARCHITECTURE §5.8) | El job `plan` termina `success` y el log muestra un `Arn` que empieza por `arn:aws:sts::648617469176:assumed-role/campus-locator-gha-terraform-plan/` |
| C3 | `gh api repos/<github_repo>/environments/dev` y `gh api repos/<github_repo>/environments/dev/deployment-branch-policies`; `iam get-role` de `campus-locator-gha-terraform` | `protection_rules` incluye `required_reviewers` con al menos una persona; `deployment_branch_policy.custom_branch_policies = true` y la única política es la rama `main`; el *trust policy* del rol tiene un único `sub` = `repo:<sub_repo>:environment:dev` (formato de ARCHITECTURE §5.8) (la asunción real la prueba INF-0.2 C2) |
| C4a | `iam get-role` de `campus-locator-gha-terraform-plan`, `campus-locator-gha-terraform` y `campus-locator-gha-deploy`; analiza las condiciones de `AssumeRolePolicyDocument` | Los tres confían solo en el proveedor `token.actions.githubusercontent.com`, con `aud = sts.amazonaws.com` y un único `sub` de §5.8 cada uno (`repo:<sub_repo>:pull_request`, `…:environment:dev`, `…:ref:refs/heads/main`), sin comodines `*`, con el mismo formato de `<sub_repo>` en los tres y, si C2 leyó el `sub` del token, igual al de GitHub |
| C4b | En el PR de C2, los jobs `sin-terraform` y `sin-deploy` (sin `environment`) intentan asumir `vars.AWS_ROL_TERRAFORM_ARN` y `vars.AWS_ROL_DEPLOY_ARN` | Ambos terminan `failure` en el paso de credenciales y su log contiene `Not authorized to perform sts:AssumeRoleWithWebIdentity` |
| C4c | En el mismo PR, el job `dev-desde-pr` declara `environment: dev` e intenta asumir `vars.AWS_ROL_TERRAFORM_ARN` | El job termina `failure` sin ejecutar ningún paso y su anotación dice que la rama no puede desplegar en `dev` (*environment protection rules*) |
| C5 | `budgets describe-budget --account-id 648617469176 --budget-name campus-locator-mensual`, `budgets describe-notifications-for-budget` y `budgets describe-subscribers-for-notification` de cada aviso; lee `correo_alertas` de `bootstrap/terraform.tfvars` | `BudgetType = COST`, `TimeUnit = MONTHLY`, límite `100` `USD`; exactamente tres avisos de tipo `PERCENTAGE` (Budgets omite `ThresholdType` cuando es ese, su valor por defecto): `ACTUAL` > 50, `ACTUAL` > 80 y `FORECASTED` > 100, cada uno con un suscriptor `EMAIL` = `correo_alertas` (Budgets no pide confirmación, ARCHITECTURE §3.8) |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

El script crea, por la API de GitHub, la rama `validacion-0-1-<AAAAMMDD-HHMMSS>`, el archivo
`.github/workflows/validacion-0-1.yml` dentro de ella y un PR con título `validacion-0-1 <AAAAMMDD-HHMMSS>`. El archivo
nunca llega a `main` y el PR no toca `INFRASTRUCTURA_TERRAFORM/project/**`, así que no dispara `infra.yml`. Al terminar
(también si algo falló, salvo `--sin-limpieza`): cancela la ejecución si sigue en curso o esperando aprobación
(`gh run cancel <id>`), cierra el PR y borra la rama (`gh pr close <n> --delete-branch`). Al empezar busca restos de
ejecuciones anteriores (PR abiertos con `headRefName` que empieza por `validacion-0-1-` en
`gh pr list --state open --json number,headRefName`, y ramas con ese prefijo en `gh api repos/<github_repo>/branches`)
y los cierra y borra igual. En AWS no crea nada: solo lee.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate01.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11); sesión de `gh` (P3) de la cuenta dueña del repositorio, porque P5 lee sus variables; ejecución desde un clon del
repositorio (P1) con `terraform -chdir=bootstrap init` hecho. La región es `us-east-1` (§5.3). Duración aproximada:
5–10 min (runners de GitHub).
