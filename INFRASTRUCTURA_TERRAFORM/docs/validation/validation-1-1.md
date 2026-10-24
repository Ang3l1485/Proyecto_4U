# Validación 1-1 — INF-1.1 Red y grupos de seguridad

| Campo | Valor |
|---|---|
| Lote | `INF-1.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate11.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

El script evalúa primero P2 (credenciales: código 3, según §5.11) y luego P1 (código 2: el lote queda `Bloqueado`); si
una falla, no sigue. P1 da 2 solo si falta el bucket o el estado de `dev`; si `init` falla por la copia local (lock,
versión de Terraform, módulos, red) o `head-object` falla por otra causa, es código 3.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-0.2` en «Hecho»: `envs/dev` con estado remoto | `terraform -chdir=envs/dev init -input=false -lockfile=readonly` termina con 0 y `s3api head-object --bucket campus-locator-tfstate-648617469176 --key dev/terraform.tfstate` responde 200 |
| P2 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

Los recursos se localizan por su etiqueta `Name` o su nombre de grupo (§5.1); solo C5 lee outputs.

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | `terraform -chdir=envs/dev plan -input=false -detailed-exitcode -lock-timeout=60s` | Código de salida 0 (2 = hay cambios, también si solo cambian outputs; 1 = error) |
| C2a | `ec2 describe-vpcs --filters Name=tag:Name,Values=campus-locator-dev-vpc`; `ec2 describe-vpc-attribute` con `enableDnsSupport` y `enableDnsHostnames` | Exactamente una VPC, `CidrBlock = 10.20.0.0/16`, ambos atributos en `true` |
| C2b | `ec2 describe-subnets --filters Name=vpc-id,Values=<vpc>` | Exactamente cuatro: `campus-locator-dev-publica-a` `10.20.0.0/24` y `campus-locator-dev-privada-a` `10.20.10.0/24` en `us-east-1a`; `campus-locator-dev-publica-b` `10.20.1.0/24` y `campus-locator-dev-privada-b` `10.20.11.0/24` en `us-east-1b` |
| C2c | `ec2 describe-route-tables`, `ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=<vpc>` y `ec2 describe-nat-gateways --filter Name=vpc-id,Values=<vpc>` | Un único IGW; las dos públicas comparten tabla y esa tabla tiene `0.0.0.0/0` hacia el IGW, activa; las tablas de las dos privadas (asociadas o la principal) solo tienen la ruta `local` (ninguna hacia IGW, NAT o endpoint); ningún NAT Gateway en estado `pending` o `available` |
| C2d | `ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc> Name=service-name,Values=com.amazonaws.us-east-1.s3` | Un único endpoint `VpcEndpointType = Gateway`, `State = available`, con `RouteTableIds` = solo la tabla pública |
| C2e | Las mismas consultas de C2a–C2d y C3: VPC, cuatro subredes, IGW, tablas asociadas a las subredes (la principal no la crea este lote), endpoint de S3, los cinco grupos, el `default` y las reglas de los cinco grupos | Todos llevan las cuatro etiquetas de §5.1 (`Proyecto = campus-locator`, `Entorno = dev`, `GestionadoPor = terraform`, `Carpeta = INFRASTRUCTURA_TERRAFORM`) y, salvo las reglas, `Name` = su nombre de §5.1 (`-vpc`, `-publica-a`…, `-igw`, `-publica`, `-privada`, `-s3`, el nombre del grupo, `-default`) |
| C3a | `ec2 describe-security-groups --filters Name=vpc-id,Values=<vpc>` y `ec2 describe-security-group-rules --filters Name=group-id,Values=<ids>`; normaliza cada regla a (grupo, sentido, protocolo, puertos, origen o destino), con `IpProtocol = -1` como «todo» sin puertos | Existen los cinco y el conjunto de reglas es exactamente el de §5.7, sin reglas de más: `vpclink` solo salida `8000/tcp` → `api`; `api` entrada `8000/tcp` ← `vpclink` y salida todo → `0.0.0.0/0`; `worker` solo salida todo → `0.0.0.0/0`; `embedding` entrada `8080/tcp` ← `api` y ← `worker`, salida todo → `0.0.0.0/0`; `rds` entrada `5432/tcp` ← `api` y ← `worker`, sin salida |
| C3b | Las mismas consultas, para el grupo `default` de la VPC | Existe uno y no tiene ninguna regla, ni entrante ni saliente |
| C4 | Las mismas consultas, para todos los grupos de la VPC (los cinco, el `default` y cualquier otro) | Ninguna regla con `IsEgress = false` tiene `CidrIpv4 = 0.0.0.0/0` ni `CidrIpv6 = ::/0` |
| C5 | `terraform -chdir=envs/dev output -json` | `subredes_tareas` = [ID de `campus-locator-dev-publica-a`] y `sg_migrate` = ID de `campus-locator-dev-api` |

`--solo` admite los alias `C2` (C2a–C2e) y `C3` (C3a y C3b).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos de prueba ni modifica recursos: solo lee la API de EC2 y los outputs, y ejecuta un `plan`, que toma y
libera el bloqueo del estado. Si se interrumpe con Ctrl+C durante el `plan`, el script reenvía la interrupción a
`terraform` (SIGINT; CTRL_BREAK en Windows) y espera hasta 120 s a que termine, ignorando mientras tanto más Ctrl+C,
SIGTERM y SIGHUP; si no termina, lo mata y avisa de que puede quedar `dev/terraform.tfstate.tflock`. Si el script muere
sin poder avisar (SIGKILL), `terraform` sigue en su propia sesión, termina el `plan` y libera el bloqueo él solo. No hay
restos que buscar al empezar.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11); para los pasos 4 y 5 de la preparación, sesión de `gh`
de la cuenta dueña del repositorio, revisora del entorno `dev`. La región es `us-east-1` (§5.3). Los comandos van
desde la raíz del repositorio.

**Preparación** (una sola vez, al cerrar el lote). El validador comprueba la red **después** del `apply` desde `main`:
sin él termina con código 1 (C1 falla con `Plan: 29 to add…` y C2a–C5 con `no existe la VPC con Name =
campus-locator-dev-vpc`).

1. Comprobar que no hay otra VPC con el nombre del lote (restos de un intento anterior, R11) y que queda cupo:
   ```bash
   aws ec2 describe-vpcs --region us-east-1 \
     --query 'Vpcs[].[VpcId,CidrBlock,IsDefault,Tags[?Key==`Name`]|[0].Value]' --output table
   ```
   Esperado: ninguna fila `campus-locator-dev-vpc` y menos de 5 VPC (cuota por defecto). Lo normal es que solo esté la
   VPC por defecto (`172.31.0.0/16`, `True`). Si aparece `campus-locator-dev-vpc`, parar y revisarla antes de seguir.
2. Comprobaciones locales y `plan`:
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|^Changes to Outputs|^  \+ (sg_migrate|subredes_tareas)'
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 29 to add, 0 to change, 0 to destroy.` y
   `Changes to Outputs:` con `+ sg_migrate` y `+ subredes_tareas`. Un *push* directo a `main` no tiene `plan` en un PR
   (§3.9): este es el que revisa quien aprueba el paso 4.
3. Commit y *push* a `main` del módulo, `envs/dev`, el validador y `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/red INFRASTRUCTURA_TERRAFORM/project/envs/dev \
     INFRASTRUCTURA_TERRAFORM/project/src/ops/validate11.py INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-1.1: red y grupos de seguridad"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/` ni `.validacion/`. En GitHub arranca `infra.yml`
   y su job `apply (main)` queda esperando la aprobación del entorno `dev`.
4. Aprobar el `apply` (o en la web: *Review deployments* → `dev` → *Approve and deploy*):
   ```bash
   SHA=$(git rev-parse HEAD)
   until RUN=$(gh run list --workflow infra.yml --branch main --event push --commit "$SHA" --limit 1 \
     --json databaseId -q '.[0].databaseId') && [ -n "$RUN" ]; do sleep 5; done
   until ENV_ID=$(gh api "repos/{owner}/{repo}/actions/runs/$RUN/pending_deployments" -q '.[0].environment.id') \
     && [ -n "$ENV_ID" ]; do sleep 5; done
   gh api -X POST "repos/{owner}/{repo}/actions/runs/$RUN/pending_deployments" \
     -F "environment_ids[]=$ENV_ID" -f state=approved -f comment="INF-1.1"
   gh run watch "$RUN" --exit-status
   gh run view "$RUN" --log | grep 'Apply complete'
   ```
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 29 added, 0 changed, 0 destroyed.`
5. Copiar los outputs nuevos a las variables del repositorio (§5.9):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   gh variable set SUBREDES_TAREAS --body "$(terraform -chdir=envs/dev output -json subredes_tareas \
     | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))')"
   gh variable set SG_MIGRATE --body "$(terraform -chdir=envs/dev output -raw sg_migrate)"
   gh variable list | grep -E 'SUBREDES_TAREAS|SG_MIGRATE'
   cd ../..
   ```
   Esperado: `SUBREDES_TAREAS  subnet-…` y `SG_MIGRATE  sg-…`.

**Ejecución:**

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate11.py --entorno dev
```

Esperado: `[PASA]` en P2, P1, C1, C2a–C2e, C3a, C3b, C4 y C5 y `Resultado: pasa (código 0)`. Duración aproximada:
1–3 min (casi todo es el `plan`).
