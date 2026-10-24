# Validación 1-3 — INF-1.3 Cómputo

| Campo | Valor |
|---|---|
| Lote | `INF-1.3` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate13.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P3 es de credenciales: código 3,
según §5.11).

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
| C1a | `ecr describe-images --image-ids imageTag=bootstrap` en `campus-locator/backend` y `campus-locator/embedding`. Guarda `desiredCount` de `ecs describe-services --cluster campus-locator-dev --services api`; si es 0 lo sube a 1 (`ecs update-service --desired-count 1`); `aws ecs wait services-stable` (máx. 10 min) y `ecs describe-tasks` de la tarea en marcha | La imagen `bootstrap` existe en los dos repositorios; `runningCount = 1`, el despliegue está `COMPLETED` y la tarea tiene `healthStatus = HEALTHY` |
| C1b | `servicediscovery list-namespaces` (`campus-locator.local`, tipo `DNS_PRIVATE`), `list-services` y `get-service` del servicio `api`; `servicediscovery list-instances` y `discover-instances --namespace-name campus-locator.local --service-name api --health-status HEALTHY` | `DnsConfig.DnsRecords` incluye `SRV`; hay una instancia con `AWS_INSTANCE_IPV4` = IP privada de la tarea y `AWS_INSTANCE_PORT = 8000`, devuelta como sana |
| C2 | Guarda `desiredCount` de `embedding`; si es 0 lo sube a 1 y espera `services-stable`. Lanza la tarea de validación con `nslookup embedding.campus-locator.local` | `app` sale con 0 y el log contiene una `Address` igual a la IP privada de la tarea de `embedding`; `get-service` de `embedding` tiene un registro `A` con `TTL = 10` |
| C3a | `iam simulate-principal-policy` de cada rol de tarea con las acciones de §5.8 sobre sus recursos: `api` `s3:PutObject`/`s3:GetObject` en `dataset/x.jpg`, `thumbs/x.jpg`, `lugares/x.jpg`, `sqs:SendMessage` en `purga` e `ingesta`, `ssmmessages:CreateControlChannel` en `*`; `worker` `s3:GetObject`/`PutObject`/`DeleteObject` en los tres prefijos, `s3:ListBucket` sobre el bucket con `--context-entries` `s3:prefix` = `dataset/x`, y las cuatro acciones de SQS en `ingesta` y `purga` | Todas dan `EvalDecision = allowed` |
| C3b | Misma simulación con acciones no concedidas: `s3:DeleteObject` y `s3:ListBucket` para `api`; `s3:GetObject` en `evaluacion/x.jpg`; `s3:ListBucket` del `worker` con `s3:prefix` = `evaluacion/x`; `sqs:SendMessage` del `worker`; `sqs:ReceiveMessage` de `api`; cualquier acción sobre las DLQ, el bucket `campus-locator-tfstate-648617469176` y `secretsmanager:GetSecretValue` de los tres secretos; `ecs:RunTask` e `iam:PassRole`. Para `embedding` y `migrate`, todas las de C3a y C3b. Además `iam list-attached-role-policies` y `list-role-policies` | Todas dan `implicitDeny` o `explicitDeny`; `campus-locator-dev-tarea-embedding` y `campus-locator-dev-tarea-migrate` no tienen políticas adjuntas ni en línea |
| C4 | `terraform -chdir=envs/dev output -json` y `terraform -chdir=bootstrap output -json`; contrasta con `ecs describe-clusters`, `ec2 describe-subnets`, `ec2 describe-security-groups`, `sqs get-queue-url`, `rds describe-db-instances`, `secretsmanager describe-secret` y `ecr describe-repositories` | Están todas las claves de §5.2 salvo `api_base_url` y `sns_alertas_arn` (las crean INF-1.4 e INF-3.1), con valores coherentes: `ecs_cluster = campus-locator-dev`; `ecs_servicios` y `familias_tarea` con los nombres de §5.1; `subredes_tareas` = [ID de `publica-a`]; `sg_migrate` = ID de `campus-locator-dev-api`; las cuatro URL de SQS; `rds_endpoint` = `Endpoint.Address`; `secretos` con `db`, `jwt` y `admin_inicial`; `embedding_dns = embedding.campus-locator.local`; `ecr_backend_url` y `ecr_embedding_url` = `repositoryUri`; y los cinco de `bootstrap` |
| C5 | Lanza la tarea de validación con un `sh -c` que ejecuta `psql "sslmode=require" -v ON_ERROR_STOP=1` con `SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()`, `CREATE EXTENSION IF NOT EXISTS vector` y `SELECT extversion FROM pg_extension WHERE extname = 'vector'`, y después `! psql "sslmode=disable" -c 'SELECT 1'` (el `!` hace que el rechazo cuente como éxito) | `app` sale con 0; el log muestra `ssl = t` y `extversion` ≥ 0.8.0, y la conexión sin TLS es rechazada (`no pg_hba.conf entry` … `no encryption`) |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Si `api` o `embedding` tenían `desiredCount = 0`, el script los sube a 1 y al terminar los devuelve a 0
(`ecs update-service --desired-count 0`); si ya estaban en 1 no los toca (Terraform ignora `desired_count`,
ADR-INF-09). Las tareas de validación llevan `startedBy = validacion-1-3` y terminan solas; en la limpieza, y al
empezar por si quedan de otra ejecución, `ecs list-tasks --cluster campus-locator-dev --started-by validacion-1-3
--desired-status RUNNING` y `ecs stop-task` de cada una. La extensión `vector` no se borra: es la misma que crea la
primera migración del backend (`IF NOT EXISTS`). La simulación de IAM no crea nada.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate13.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con permiso para `ecs:RunTask`, `ecs:UpdateService` e
`iam:PassRole` sobre los roles de §5.8. La región es `us-east-1` (§5.3). Si INF-2.1 ya está aplicado, ejecútese
dentro del horario (06:00–22:00, `America/Bogota`). Duración aproximada: 10–15 min.
