# Validación 1-3 — INF-1.3 Cómputo

| Campo | Valor |
|---|---|
| Lote | `INF-1.3` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate13.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

El script evalúa primero P3 (credenciales: código 3, según §5.11), luego P1 y P2 (código 2: el lote queda
`Bloqueado`); si una falla, no sigue. Los outputs los lee con `terraform -chdir=envs/dev output -json` (P2 y C4) y
`terraform -chdir=bootstrap output -json` (C4): hace falta `init` en esa copia; el resto lo lee de las API de AWS.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.2` en «Hecho»: base, secreto `db` y colas | `rds describe-db-instances --db-instance-identifier campus-locator-dev-db` da `DBInstanceStatus = available`; `secretsmanager describe-secret --secret-id campus-locator/dev/db` responde; `sqs get-queue-url` responde para `campus-locator-dev-ingesta` y `campus-locator-dev-purga` |
| P2 | Outputs para lanzar la tarea de validación | `terraform -chdir=envs/dev output -json` contiene `ecs_cluster`, `familias_tarea` (con la clave `validacion`), `subredes_tareas` y `sg_migrate` |
| P3 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

La tarea de validación se lanza siempre igual: `ecs run-task --cluster campus-locator-dev --task-definition
campus-locator-dev-validacion --launch-type FARGATE --started-by validacion-1-3`, red `subredes_tareas` + `sg_migrate`
con `assignPublicIp=ENABLED` y el comando del contenedor `app` sobrescrito; después `ecs wait tasks-stopped`,
`ecs describe-tasks` (código de salida de `app`) y `logs filter-log-events --log-group-name
/campus-locator/dev/validacion`
sobre el stream cuyo nombre termina en el ID de la tarea.

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `ecr describe-images --image-ids imageTag=bootstrap` en `campus-locator/backend` y `campus-locator/embedding` (si falta, falla sin tocar los servicios: hay que publicarla, `pruebas/imagen-prueba/README.md`). Guarda `desiredCount` de `ecs describe-services --cluster campus-locator-dev --services api`; si es 0 lo sube a 1 (`ecs update-service --desired-count 1`); `aws ecs wait services-stable` (máx. 10 min) y `ecs describe-tasks` de la tarea en marcha | La imagen `bootstrap` existe en los dos repositorios; `runningCount = 1`, el despliegue está `COMPLETED` y la tarea tiene `healthStatus = HEALTHY` |
| C1b | `servicediscovery list-namespaces` (`campus-locator.local`, tipo `DNS_PRIVATE`), `list-services` y `get-service` del servicio `api`; `servicediscovery list-instances` y `discover-instances --namespace-name campus-locator.local --service-name api --health-status HEALTHY` | `DnsConfig.DnsRecords` incluye `SRV`; hay una instancia con `AWS_INSTANCE_IPV4` = IP privada de la tarea y `AWS_INSTANCE_PORT = 8000`, devuelta como sana |
| C2 | Guarda `desiredCount` de `embedding`; si es 0 lo sube a 1 y espera `services-stable` (máx. 10 min). Lanza la tarea de validación con `nslookup embedding.campus-locator.local` | `app` sale con 0 y el log contiene una `Address` igual a la IP privada de la tarea de `embedding`; `get-service` de `embedding` tiene un registro `A` con `TTL = 10` |
| C3a | `iam simulate-principal-policy` de cada rol de tarea con las acciones de §5.8 sobre sus recursos: `api` `s3:PutObject`/`s3:GetObject` en `dataset/x.jpg`, `thumbs/x.jpg`, `lugares/x.jpg`, `sqs:SendMessage` en `purga` e `ingesta`, `ssmmessages:CreateControlChannel` en `*`; `worker` `s3:GetObject`/`PutObject`/`DeleteObject` en los tres prefijos, `s3:ListBucket` sobre el bucket con `--context-entries` `s3:prefix` = `dataset/x`, y las cuatro acciones de SQS en `ingesta` y `purga` | Todas dan `EvalDecision = allowed` |
| C3b | Misma simulación con acciones no concedidas: `s3:DeleteObject` y `s3:ListBucket` para `api`; `s3:GetObject` en `evaluacion/x.jpg`; `s3:ListBucket` del `worker` con `s3:prefix` = `evaluacion/x`; `sqs:SendMessage` del `worker`; `sqs:ReceiveMessage` de `api`; cualquier acción sobre las DLQ, el bucket `campus-locator-tfstate-648617469176` y `secretsmanager:GetSecretValue` de los tres secretos; `ecs:RunTask` e `iam:PassRole`. Para `embedding` y `migrate`, todas las de C3a y C3b. Además `iam list-attached-role-policies` y `list-role-policies` | Todas dan `implicitDeny` o `explicitDeny`; `campus-locator-dev-tarea-embedding` y `campus-locator-dev-tarea-migrate` no tienen políticas adjuntas ni en línea |
| C4 | `terraform -chdir=envs/dev output -json` y `terraform -chdir=bootstrap output -json`; contrasta con `ecs describe-clusters`, `ec2 describe-subnets`, `ec2 describe-security-groups`, `sqs get-queue-url`, `rds describe-db-instances`, `secretsmanager describe-secret` y `ecr describe-repositories` | Están todas las claves de §5.2 salvo `api_base_url` y `sns_alertas_arn` (las crean INF-1.4 e INF-3.1), con valores coherentes: `ecs_cluster = campus-locator-dev`; `ecs_servicios` y `familias_tarea` con los nombres de §5.1; `subredes_tareas` = [ID de `publica-a`]; `sg_migrate` = ID de `campus-locator-dev-api`; las cuatro URL de SQS; `rds_endpoint` = `Endpoint.Address`; `secretos` con `db`, `jwt` y `admin_inicial`; `embedding_dns = embedding.campus-locator.local`; `ecr_backend_url` y `ecr_embedding_url` = `repositoryUri`; y los seis de `bootstrap` (los tres roles existen, `bucket_estado`, `github_repo` y `limite_roles_arn`). Además, `iam get-role` de `campus-locator-dev-ecs-ejecucion` y de los cuatro `tarea-*`: los cinco llevan ese *boundary* (ADR-INF-12) |
| C5 | Lanza la tarea de validación con un `sh -c` que ejecuta `psql "sslmode=require" -v ON_ERROR_STOP=1` con `SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()`, `CREATE EXTENSION IF NOT EXISTS vector` y `SELECT extversion FROM pg_extension WHERE extname = 'vector'`, y después `! psql "sslmode=disable" -c 'SELECT 1'` (el `!` hace que el rechazo cuente como éxito) | `app` sale con 0; el log muestra `SSL=true` (`ssl` concatenado a texto) y `extversion` ≥ 0.8.0, y la conexión sin TLS es rechazada (`no pg_hba.conf entry` … `no encryption`) |
| C6 | Con `embedding` en 1 (de C2): `ecs describe-tasks` de su tarea | `launchType = FARGATE`, `cpu = 2048`, `memory = 4096` y `healthStatus = HEALTHY` (§3.4) |

`--solo` admite los alias `C1` (C1a y C1b) y `C3` (C3a y C3b). C1a, C2 y C6 comparten el encendido: cada servicio se
sube a 1 una sola vez por ejecución. `services-stable` no espera al *health check*, así que tras él el script espera
hasta 5 min a que la tarea esté `HEALTHY` (el *start period* de `embedding` es de 180 s). Ninguna salida de la tarea de
validación se imprime: el script solo extrae de su log las direcciones de `nslookup` y las líneas `SSL=`, `VECTOR=` y
`SIN_TLS=`.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Si `api` o `embedding` tenían `desiredCount = 0`, el script los sube a 1 y al terminar los devuelve a 0 (`ecs
update-service --desired-count 0`); si ya estaban en 1 no los toca (Terraform ignora `desired_count`, ADR-INF-09).
Las tareas de validación llevan `startedBy = validacion-1-3` y terminan solas; en la limpieza, y al
empezar por si quedan de otra ejecución, `ecs list-tasks --cluster campus-locator-dev --started-by validacion-1-3
--desired-status RUNNING` y `ecs stop-task` de cada una. La extensión `vector` no se borra: es la misma que crea la
primera migración del backend (`IF NOT EXISTS`). La simulación de IAM no crea nada.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con lectura del bucket de estado (`terraform output`);
`ecs:DescribeClusters`, `DescribeServices`, `UpdateService`, `ListTasks`, `DescribeTasks`, `RunTask`, `StopTask` y
`DescribeTaskDefinition` sobre `campus-locator-dev`; `iam:PassRole` sobre `campus-locator-dev-ecs-ejecucion` y
`campus-locator-dev-tarea-migrate`; `iam:SimulatePrincipalPolicy`, `GetRole`, `ListAttachedRolePolicies` y
`ListRolePolicies`; lectura de Cloud Map, ECR, EC2, SQS, RDS y Secrets Manager (`DescribeSecret`, sin leer valores) y
`logs:GetLogEvents` sobre `/campus-locator/dev/validacion`; para el paso 6 de la preparación, `ecr` de escritura en los
dos repositorios y Docker; para el paso 7, sesión de `gh` de la cuenta dueña del repositorio, revisora del entorno
`dev`. La región es `us-east-1` (§5.3). Los comandos van desde la raíz del repositorio, con
`export AWS_REGION=us-east-1`.

**Preparación** (una sola vez, al cerrar el lote). El validador comprueba los recursos **después** del `apply` desde
`main`: sin él termina con código 2 (P2: `INF-1.3 no está aplicado en envs/dev: faltan los outputs …`), y sin la
imagen de prueba, C1a, C2 y C6 fallan con `falta la imagen de prueba en …`.

1. Comprobar que ningún nombre del lote está ocupado (restos de un intento anterior, R11):
   ```bash
   aws servicediscovery list-namespaces --query "Namespaces[?Name=='campus-locator.local'].[Id,Type]" --output text
   aws ecs describe-clusters --clusters campus-locator-dev --query "clusters[?status=='ACTIVE'].clusterName" --output text
   aws ecr describe-repositories --query "repositories[?starts_with(repositoryName,'campus-locator')].repositoryName" \
     --output text
   aws iam list-roles --query "Roles[?starts_with(RoleName,'campus-locator-dev-')].RoleName" --output text
   aws logs describe-log-groups --log-group-name-prefix /campus-locator/dev/ --query 'logGroups[].logGroupName' \
     --output text
   aws ecs list-task-definition-families --family-prefix campus-locator-dev --status ACTIVE --output text
   ```
   Esperado: ninguno imprime nada. Si aparece cualquiera de los nombres de §5.1 del lote, parar y revisarlo antes de
   seguir (un *namespace* `campus-locator.local` de otra VPC también choca).
2. Comprobaciones locales y `plan` (este lote no añade proveedores: `terraform_remote_state` es interno de Terraform y
   el lock no cambia):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|^  \+ (ecr_|ecs_|familias_tarea|embedding_dns)'
   git diff --exit-code envs/dev/.terraform.lock.hcl && echo LOCK_SIN_CAMBIOS
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 30 to add, 0 to change, 0 to destroy.`, las seis
   líneas `+ ecr_backend_url`, `+ ecr_embedding_url`, `+ ecs_cluster`, `+ ecs_servicios`, `+ embedding_dns` y
   `+ familias_tarea`, y `LOCK_SIN_CAMBIOS`. Ningún recurso existente cambia. Un *push* directo a `main` no tiene
   `plan` en un PR (§3.9): este es el que revisa quien aprueba el paso 4.
3. Commit y *push* a `main` del módulo, `envs/dev`, `modules/datos` (comentario), la imagen de prueba, el validador y
   `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/computo INFRASTRUCTURA_TERRAFORM/project/modules/datos \
     INFRASTRUCTURA_TERRAFORM/project/envs/dev INFRASTRUCTURA_TERRAFORM/project/pruebas \
     INFRASTRUCTURA_TERRAFORM/project/src/ops/validate13.py INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-1.3: computo"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/` ni `.validacion/`. En GitHub arranca `infra.yml`
   y su job `apply (main)` queda esperando la aprobación del entorno `dev` (si hay otra ejecución de `main` de un
   commit anterior esperando, retiene la fila: cancelarla).
4. Aprobar el `apply`: igual que el paso 4 de [`validation-1-1`](./validation-1-1.md) §5, con `comment="INF-1.3"`.
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 30 added, 0 changed, 0 destroyed.`
   Los servicios se crean en 0 réplicas: no hace falta la imagen todavía.
5. Comprobar que no quedan diferencias (una definición de tarea que ECS normaliza distinto daría cambios en cada
   `plan`):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -detailed-exitcode -no-color | grep -E '^(No changes|Plan:)'
   echo "codigo=${PIPESTATUS[0]}"
   ```
   Esperado: `No changes. Your infrastructure matches the configuration.` y `codigo=0`.
6. Publicar la imagen de prueba en los dos repositorios (`project/pruebas/imagen-prueba/README.md`):
   ```bash
   REGISTRO=648617469176.dkr.ecr.us-east-1.amazonaws.com
   aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRO"
   docker build --platform linux/amd64 -t campus-locator-imagen-prueba pruebas/imagen-prueba
   for repo in backend embedding; do
     docker tag campus-locator-imagen-prueba "$REGISTRO/campus-locator/$repo:bootstrap"
     docker push "$REGISTRO/campus-locator/$repo:bootstrap"
   done
   ```
   Esperado: `Login Succeeded` y dos `bootstrap: digest: sha256:… size: …`. Si una dice `tag invalid: The image tag
   'bootstrap' already exists`, ya estaba publicada: no hace falta repetirla (etiquetas inmutables).
7. Copiar los outputs nuevos a las variables del repositorio (§5.9):
   ```bash
   for par in ECR_BACKEND:ecr_backend_url ECR_EMBEDDING:ecr_embedding_url ECS_CLUSTER:ecs_cluster; do
     gh variable set "${par%%:*}" --body "$(terraform -chdir=envs/dev output -raw "${par#*:}")"
   done
   gh variable list | grep -E '^(ECR_|ECS_CLUSTER)'
   cd ../..
   ```
   Esperado: las tres variables con `…/campus-locator/backend`, `…/campus-locator/embedding` y `campus-locator-dev`.

**Ejecución** (antes de las 21:40 `America/Bogota` una vez aplicado INF-2.1, para que el apagado de las 22:00 no
ponga `embedding` en 0 a mitad). Desde INF-2.1, encender `embedding` antes con `uv run --group ops python
src/ops/embedding.py encender` y apagarlo al terminar con `embedding.py apagar`: C2 y C6 lo suben con
`update-service`, y la alarma de inactividad, si está en `ALARM`, lo devolvería a 0 en un minuto (ARCHITECTURE §3.4);
encendido, `validate13.py` lo encuentra en 1 y no lo toca:

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate13.py --entorno dev
```

Esperado: `[PASA]` en P3, P1, P2, C1a, C1b, C2, C3a, C3b, C4, C5 y C6 y `Resultado: pasa (código 0)`; en stderr,
`limpieza hecha: devolver el servicio api a 0 réplicas` (y lo mismo con `embedding`) si estaban en 0. Duración
aproximada: 10–15 min (casi todo es el arranque de `api` y `embedding` y las dos tareas de validación).
