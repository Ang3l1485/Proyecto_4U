# Validación 0-2 — INF-0.2 Esqueleto de `envs/dev` y CI de Terraform

| Campo | Valor |
|---|---|
| Lote | `INF-0.2` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate02.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina y no sigue con las demás. P3 a P6 son credenciales, herramientas o
configuración local (código 3, según §5.11) y se evalúan primero; P1 y P2 dependen de INF-0.1 (código 2: el lote queda
`Bloqueado`).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-0.1` en «Hecho»: bucket de estado y roles de GitHub | `terraform -chdir=bootstrap output -json` contiene `bucket_estado` (= `campus-locator-tfstate-648617469176`, el de `envs/dev/backend.tf`), `rol_gha_terraform_plan_arn`, `rol_gha_terraform_arn` y `rol_gha_deploy_arn`, y su `github_repo` es el de P4; `iam get-role` responde para `campus-locator-gha-terraform-plan` y `campus-locator-gha-terraform` |
| P2 | `INF-0.1` en «Hecho»: variables del repositorio que usa `infra.yml` | `gh variable list --json name,value` contiene `AWS_REGION` = `us-east-1` y `AWS_ROL_TERRAFORM_PLAN_ARN` y `AWS_ROL_TERRAFORM_ARN` con los valores de P1 |
| P3 | Credenciales de la cuenta `648617469176` | `sts get-caller-identity` (perfil `AWS_PROFILE`) devuelve `Account = 648617469176` |
| P4 | `gh` autenticado sobre el repositorio | `gh auth status` termina con 0 y la cuenta activa tiene los *scopes* `repo` y `workflow`; `gh repo view --json nameWithOwner,defaultBranchRef` da el `<github_repo>` con rama por defecto `main` |
| P5 | Terraform con bloqueo nativo en S3 | `terraform version -json` devuelve `terraform_version` ≥ 1.10. El detalle avisa si no es la `TF_VERSION` de `.github/workflows/infra.yml` (`fmt` puede formatear distinto entre versiones) |
| P6 | Copia local inicializada | `terraform -chdir=envs/dev state pull` termina con 0 (hecho `terraform -chdir=envs/dev init` y el *backend* accesible). El detalle dice si ya hay estado: sin él, C1 y C4b fallan (falta el primer `apply` de `main`) |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Por la API de GitHub (sin tocar la copia local) crea la rama `validacion-0-2-<AAAAMMDD-HHMMSS>` desde `main` con un único commit: el comentario `# validacion-0-2 <AAAAMMDD-HHMMSS>` al final de `INFRASTRUCTURA_TERRAFORM/project/envs/dev/main.tf` (sustituye el de una ejecución anterior si existe). Abre el PR, espera la ejecución de `infra.yml` de ese commit (`actions/workflows/infra.yml/runs?branch=<rama>&event=pull_request&head_sha=<sha>`) hasta que termine, lee los pasos de su job `plan (PR)` y los comentarios del PR | La ejecución termina `success`; los pasos `terraform fmt -check`, `tflint`, `terraform validate` y `terraform plan` terminan `success`; el PR tiene un comentario de `github-actions[bot]` con la marca `<!-- infra-plan envs/dev -->` cuya salida del `plan` contiene `No changes.` |
| C2a | Antes de fusionar comprueba que `main` sigue en el commit del que salió la rama y que no hay otra ejecución de `infra.yml` activa en `main` (si no, falla sin fusionar: el `apply` que aprueba C2b no debe llevar cambios ajenos). Fusiona el PR por la API (*squash*, título `validacion-0-2 <AAAAMMDD-HHMMSS> (#<n>)`) y borra la rama; si la protección de `main` lo impide, espera hasta 15 min a que la persona lo fusione. Comprueba que el único padre del commit fusionado es ese commit de partida (si no, falla y deja el `apply` esperando para que lo revise una persona). Busca la ejecución de `infra.yml` del evento `push` en `main` cuyo `head_sha` es el commit fusionado, espera a que quede `waiting` y consulta `actions/runs/<id>/pending_deployments` y los jobs | La ejecución está `waiting`, `pending_deployments` incluye el entorno `dev` y el job `apply (main)` no ha ejecutado ningún paso |
| C2b | Aprueba con `POST actions/runs/<id>/pending_deployments` (`state=approved`, comentario `validacion-0-2`), espera a que la ejecución termine y lee el log del job con `gh run view --log --job <id>` | El job `apply (main)` termina `success` y su log contiene `Apply complete! Resources: 0 added, 0 changed, 0 destroyed` |
| C3a | Guarda `lineage` y `serial` de `terraform -chdir=envs/dev state pull`; lanza a la vez dos `terraform -chdir=envs/dev plan -input=false -lock-timeout=120s` | Los dos terminan con 0 y `state pull` devuelve después el mismo `lineage` y `serial` |
| C3b | Toma el bloqueo como lo hace Terraform: crea `dev/terraform.tfstate.tflock` en el bucket de estado con escritura condicional (`If-None-Match: *`) y un `LockInfo` propio (`ID` aleatorio, `Who = validacion-0-2@<máquina>`, `Info = validacion-0-2 <AAAAMMDD-HHMMSS> …`); si ya existe, falla sin tocarlo. (Desde Terraform 1.15, `terraform console` ya no toma el bloqueo.) Lanza `plan -input=false -lock-timeout=0s` y, en paralelo, `plan -input=false -lock-timeout=120s`; a los 20 s borra su `.tflock` (solo si el `ID` y el `ETag` siguen siendo los suyos) | El primer `plan` falla con `Error acquiring the state lock`; el segundo sigue esperando a los 20 s, toma el bloqueo al liberarse y termina con 0; al final ya no existe el `.tflock` |
| C4a | `terraform -chdir=envs/dev plan -input=false -lock=false -var aws_account_id=000000000000`: el proveedor recibe un `allowed_account_ids` que no incluye la cuenta de las credenciales | El `plan` termina con error y el mensaje contiene `not allowed` y `648617469176` |
| C4b | Lee el bloque `provider "aws"` de `envs/dev/*.tf`, `terraform -chdir=envs/dev output -json` y `terraform -chdir=envs/dev show -json` (el estado, que nunca se imprime) | El bloque declara `allowed_account_ids` y `default_tags` con las claves `Proyecto`, `Entorno`, `GestionadoPor` y `Carpeta`; las etiquetas efectivas que guarda `data.aws_default_tags.actuales` en el estado son `Proyecto = campus-locator`, `Entorno = dev`, `GestionadoPor = terraform` y `Carpeta = INFRASTRUCTURA_TERRAFORM`; existe el output `cuenta_id` = `648617469176`; si ya hay recursos gestionados, todos los que tienen `tags_all` (también en módulos) llevan esas cuatro etiquetas |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

El script crea, por la API de GitHub, la rama `validacion-0-2-<AAAAMMDD-HHMMSS>`, su commit (mensaje
`validacion-0-2 <AAAAMMDD-HHMMSS>`), su PR (título igual) y, al fusionarlo, el commit `validacion-0-2 <…> (#<n>)` en
`main` con el comentario `# validacion-0-2 …` en `envs/dev/main.tf`. La rama se borra al fusionar. Al terminar
(también si algo falló, salvo `--sin-limpieza`), en este orden: cancela las ejecuciones de `infra.yml` que creó y sigan
activas (incluido un `apply` que no llegó a aprobarse, salvo el que C2a dejó para revisión humana), cierra el PR si
sigue abierto, borra la rama si sigue existiendo, detiene los procesos de `terraform` que sigan abiertos (SIGINT, para
que suelten el bloqueo; solo los mata si no responden) y, si queda el `dev/terraform.tfstate.tflock` que creó C3b
(mismo `ID`), lo borra (nunca un bloqueo ajeno).
El comentario fusionado queda en `main` porque C2 exige fusionar; nunca hay más de uno, porque cada ejecución sustituye
el anterior. Al empezar busca restos de ejecuciones anteriores: cierra los PR abiertos con rama `validacion-0-2-*` del propio
repositorio (no de *forks*), título `validacion-0-2 …` y autor la cuenta de `gh` (cancelando sus ejecuciones activas), borra las ramas con ese prefijo y cancela las ejecuciones de `main` que siguen
esperando aprobación y cuyo commit empieza por `validacion-0-2 ` (retendrían la fila de concurrencia de `main`). En AWS
solo crea, durante C3b, su propio `.tflock`; los `plan` no cambian el estado.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11); sesión de `gh` (P4) de la cuenta dueña del repositorio,
que además debe poder aprobar el entorno `dev` (revisora del entorno). La región es `us-east-1` (§5.3). Los comandos
van desde la raíz del repositorio.

**Preparación** (una sola vez, al cerrar el lote: sin el primer `apply` no hay estado de `envs/dev` y el `plan` de C1
no dice `No changes.`):

1. Comprobar que la clave de estado de `dev` está vacía (si hay algo, es de otro intento: parar y revisarlo):
   ```bash
   aws s3 ls s3://campus-locator-tfstate-648617469176/dev/; echo "exit=$?"
   ```
   Esperado: sin salida y `exit=1`.
2. Inicializar, fijar el lock de proveedores para todas las plataformas del equipo y comprobar en local:
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false
   terraform -chdir=envs/dev providers lock -platform=linux_amd64 -platform=windows_amd64 \
     -platform=darwin_amd64 -platform=darwin_arm64
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false
   cd ../..
   ```
   Esperado: `FMT_OK`, `Terraform has been successfully initialized!`, `Success! Terraform has updated the lock
   file.`, `Success! The configuration is valid.` y un `plan` sin recursos, solo
   `Changes to Outputs: + cuenta_id = "648617469176"`.
3. Commit y push a `main` de `infra.yml`, `envs/dev` (con `.terraform.lock.hcl`), `modules/`, `.tflint.hcl` y
   `src/ops/validate02.py`. `git status --short` no debe mostrar nada bajo `.terraform/`. En GitHub arranca `infra.yml`
   y su job `apply (main)` queda esperando la aprobación del entorno `dev`.
4. Aprobar el primer `apply` (o en la web: *Review deployments* → `dev` → *Approve and deploy*):
   ```bash
   RUN=$(gh run list --workflow infra.yml --branch main --event push --limit 1 --json databaseId -q '.[0].databaseId')
   ENV_ID=$(gh api "repos/{owner}/{repo}/actions/runs/$RUN/pending_deployments" -q '.[0].environment.id')
   gh api -X POST "repos/{owner}/{repo}/actions/runs/$RUN/pending_deployments" \
     -F "environment_ids[]=$ENV_ID" -f state=approved -f comment="primer apply de envs/dev"
   gh run watch "$RUN" --exit-status
   aws s3 ls s3://campus-locator-tfstate-648617469176/dev/
   ```
   Esperado: `gh run watch` termina con 0, el log del job `apply (main)` dice
   `Apply complete! Resources: 0 added, 0 changed, 0 destroyed.` y en `dev/` aparece `terraform.tfstate`.

**Ejecución:**

```bash
cd INFRASTRUCTURA_TERRAFORM/project
terraform -chdir=envs/dev init -input=false   # solo en una copia nueva (P6)
uv run --group ops python src/ops/validate02.py --entorno dev
cd ../.. && git pull                          # C2 deja en main el commit «validacion-0-2 … (#n)»
```

Esperado: `[PASA]` en P1–P6 y C1–C4b y `Resultado: pasa (código 0)`. Duración aproximada: 10–15 min.
