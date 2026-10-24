# `bootstrap/` — INF-0.1 Bootstrap de la cuenta

Lo mínimo para trabajar con estado remoto y CI sin llaves de larga duración (PLAN §2.3, ARCHITECTURE §3.9 y §4). Se
aplica **una sola vez**, a mano, con el usuario administrador; después solo se vuelve a aplicar si cambia algo de aquí.

| Qué | Dónde | Contrato |
|---|---|---|
| Bucket de estado `campus-locator-tfstate-648617469176` (versionado, SSE-S3, privado, solo TLS, `prevent_destroy`) | `estado.tf` | §3.9, §5.1 |
| Proveedor OIDC `token.actions.githubusercontent.com` | `oidc.tf` | §3.7 |
| Roles `campus-locator-gha-terraform-plan`, `-gha-terraform`, `-gha-deploy` (un único `sub` cada uno) | `oidc.tf`, `permisos.tf` | §5.8 |
| *Permissions boundary* `campus-locator-limite-roles`: obligatorio en todo rol `campus-locator-*` que cree `gha-terraform` (INF-1.3 debe poner `permissions_boundary` en sus roles) | `permisos.tf` | §5.8 |
| Presupuesto `campus-locator-mensual` (100 USD; avisos 50 % y 80 % real, 100 % pronosticado) | `presupuesto.tf` | §3.8, §5.10 |
| Outputs `bucket_estado`, `rol_gha_*_arn`, `limite_roles_arn`, `github_repo` | `outputs.tf` | §5.2 |
| Variables del repositorio y entorno `dev` de GitHub (fuera de Terraform) | `configurar_github.py` | §3.9, §5.9 |

## 1. Antes de empezar

**Decisiones** (`terraform.tfvars`, ARCHITECTURE §5.3). Con los marcadores `<…>` el `plan` falla a propósito:
- `github_repo`: `propietario/nombre` con las mayúsculas exactas de GitHub (`gh repo view --json nameWithOwner`).
- `correo_alertas`: el correo que recibe los avisos del presupuesto.
- `github_ids`: solo si el repositorio usa el `sub` inmutable (ver «Formato del sub»).

**Visibilidad del repositorio.** GitHub solo permite *required reviewers* en repos **públicos** (cualquier plan) o en
privados con **GitHub Enterprise**. Con un repo privado en Free, Pro o Team el entorno `dev` no puede exigir
aprobación y C3 no se cumple.

**Herramientas:** Terraform ≥ 1.10, AWS CLI v2, `gh` autenticado con `gh auth login -s repo,workflow`, `uv`.

**Higiene de la cuenta** (a mano, una vez; ARCHITECTURE §3.1):
1. Usuario raíz con MFA y **sin** llaves de acceso.
2. Un usuario administrador con MFA para el `bootstrap` (o IAM Identity Center); su perfil local es el `AWS_PROFILE`.
3. *S3 Block Public Access* a nivel de cuenta:
   ```
   aws s3control put-public-access-block --account-id 648617469176 --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

### Formato del `sub`

Desde el 2026-07-15 GitHub usa un `sub` inmutable en los repos creados, renombrados o transferidos después de esa
fecha (y en los que lo activan): `repo:propietario@ID/nombre@ID:…` en lugar de `repo:propietario/nombre:…`. Si el
*trust policy* no coincide, AWS rechaza el token (C2 falla). Para saber qué formato usa tu repositorio:

```
gh api repos/<propietario>/<nombre> --jq "{creado: .created_at, propietario: .owner.id, repositorio: .id}"
```

Si `creado` es posterior al 2026-07-15 (o el repo se renombró o transfirió después), añade a `terraform.tfvars`:

```hcl
github_ids = { propietario = <owner.id>, repositorio = <id> }
```

El validador lo confirma: el job `plan` de C2 imprime el `sub` real del token (solo el *claim*, nunca el token).

## 2. Paso a paso

En bash (Linux, WSL, macOS o Git Bash), desde `INFRASTRUCTURA_TERRAFORM/project/` y con el perfil del administrador.
En PowerShell: `$env:AWS_PROFILE = "…"`, crea `backend_override.tf` con un editor (mismo contenido de tres líneas) y
usa `Remove-Item` en lugar de `rm`.

```bash
export AWS_PROFILE=<perfil-admin>
aws sts get-caller-identity                 # Account debe ser 648617469176
```

**2.1 Primer `apply` con estado local.** El bucket aún no existe, así que `backend.tf` se anula con un archivo
`*_override.tf` (ignorado por Git):

```bash
printf 'terraform {\n  backend "local" {}\n}\n' > bootstrap/backend_override.tf   # HCL no admite el bloque en una línea
terraform -chdir=bootstrap init -reconfigure
terraform -chdir=bootstrap validate
terraform -chdir=bootstrap apply            # revisa el plan antes de responder «yes»
```

El plan debe crear 19 recursos: el bucket y 6 piezas de su configuración, el proveedor OIDC, 3 roles, 2 políticas
gestionadas de AWS adjuntas, 4 políticas en línea, el *boundary* y el presupuesto.

**2.2 Migrar el estado al bucket** (ARCHITECTURE §3.9) y borrar la copia local:

```bash
rm bootstrap/backend_override.tf
terraform -chdir=bootstrap init -migrate-state   # responde «yes» a copiar el estado
terraform -chdir=bootstrap plan                  # debe decir «No changes.»
rm -f bootstrap/terraform.tfstate*
```

**2.3 GitHub** (lo ejecuta **el dueño del repositorio**: en un repo personal solo él puede crear variables y
entornos). Crea las variables del repositorio y el entorno `dev` con aprobación manual y solo la rama `main`. Siempre
añade como revisor a quien lo ejecuta, conserva los revisores que ya hubiera y suma los de `--revisor`:

```bash
uv run python bootstrap/configurar_github.py --revisor <otro-login>
```

**2.4 Commit y PR antes de validar**, para que el informe registre el commit que se cierra (PLAN §3, «Última
validación»). Versiona `bootstrap/*.tf`, `terraform.tfvars`, `.terraform.lock.hcl` (la que creó `init`), los `.py`,
`pyproject.toml` y `.gitignore`. Nunca `*.tfstate*`, `.terraform/` ni `backend_override.tf` (ya ignorados).

```bash
terraform fmt -recursive
git switch -c inf-0.1 && git add -A . && git status   # revisa que no entre nada de lo anterior
git commit -m "INF-0.1: bootstrap de la cuenta" && git push -u origin inf-0.1
gh pr create --fill
```

**2.5 Validar** (docs/validation/validation-0-1.md, 5–10 min). Lee las variables del repositorio, así que también lo
ejecuta el dueño (o alguien con su permiso). Deja el informe de `.validacion/` como evidencia en el PR:

```bash
uv run --group ops python src/ops/validate01.py --entorno dev
```

## 3. Problemas frecuentes

| Síntoma | Causa y arreglo |
|---|---|
| `EntityAlreadyExists` al crear el proveedor OIDC | La cuenta ya tiene uno para GitHub: `terraform -chdir=bootstrap import aws_iam_openid_connect_provider.github arn:aws:iam::648617469176:oidc-provider/token.actions.githubusercontent.com` |
| `BucketAlreadyOwnedByYou` | El bucket se creó antes: `terraform -chdir=bootstrap import aws_s3_bucket.estado campus-locator-tfstate-648617469176` |
| C2: `Not authorized to perform sts:AssumeRoleWithWebIdentity` en el job `plan` | Formato del `sub` o mayúsculas de `github_repo`: compara el `sub` que imprime el validador con el del rol |
| `configurar_github.py` deja el entorno sin revisores | Repo privado sin Enterprise (ver §1) |
| `configurar_github.py` o el validador dan HTTP 403 | La cuenta de `gh` no es la dueña del repositorio (ver 2.3) |
| INF-1.3: `AccessDenied` en `iam:CreateRole` | El rol no lleva `permissions_boundary = <limite_roles_arn>` |
| Hay que destruir el bucket | Tiene `prevent_destroy`: quitarlo es una decisión explícita, nunca parte de un cambio rutinario |
