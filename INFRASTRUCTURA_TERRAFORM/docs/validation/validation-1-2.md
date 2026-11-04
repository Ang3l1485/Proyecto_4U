# Validación 1-2 — INF-1.2 Datos y secretos

| Campo | Valor |
|---|---|
| Lote | `INF-1.2` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate12.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

El script evalúa primero P2 (credenciales: código 3, según §5.11) y luego P1 (código 2: el lote queda `Bloqueado`); si
una falla, no sigue. No usa Terraform: todo lo lee de las API de AWS.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.1` en «Hecho»: VPC, subredes privadas y grupos que usa RDS | `ec2 describe-vpcs --filters Name=tag:Name,Values=campus-locator-dev-vpc` devuelve una; dentro de esa VPC, `ec2 describe-subnets` devuelve una `campus-locator-dev-privada-a` y una `campus-locator-dev-privada-b`, y `ec2 describe-security-groups` devuelve `campus-locator-dev-rds`, `-api` y `-worker` |
| P2 | Credenciales de la cuenta `648617469176`, con lectura de secretos | `aws sts get-caller-identity` devuelve `Account = 648617469176`; `secretsmanager list-secrets` no da `AccessDenied` |

Los recursos del lote se localizan por nombre (§5.1): bucket `campus-locator-dev-dataset-648617469176`, colas con
`sqs get-queue-url --queue-name …`, instancia `campus-locator-dev-db`, grupos `campus-locator-dev-pg17` (parámetros) y
`campus-locator-dev-db` (subredes) y secretos `campus-locator/dev/…`. Los outputs de §5.2 se exigen en INF-1.3 (C4).

## 2. Comprobaciones automáticas

`<sello>` = `AAAAMMDD-HHMMSS` (UTC) del inicio de la ejecución.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Antes de subir nada: comprueba que nadie consume `ingesta` y que la cola solo tiene restos de prueba o el `s3:TestEvent` (§4; si no, falla sin subir) y borra los restos de ejecuciones anteriores. Sube con `s3api put-object` un JPEG de 8×8 px generado en memoria a `dataset/validacion-<sello>/c1.jpg` y lee `campus-locator-dev-ingesta` (`sqs receive-message --wait-time-seconds 20 --max-number-of-messages 10 --visibility-timeout 300`) durante 90 s como máximo | Llega un mensaje con `Records[0].eventName` que empieza por `ObjectCreated:`, `s3.bucket.name` = el bucket y `s3.object.key` (decodificada con `unquote_plus`) = la clave subida |
| C2 | Antes del objeto de C1 sube `dataset/validacion-<sello>/c2.png` y `thumbs/validacion-<sello>/c2.jpg`; revisa todo mensaje recibido mientras espera el de C1 y durante 30 s más | Llegó el evento de C1 (sin él, que no lleguen los de c2 no prueba los filtros) y ningún mensaje menciona `dataset/validacion-<sello>/c2.png` ni `thumbs/validacion-<sello>/c2.jpg` |
| C3a | `rds describe-db-instances --db-instance-identifier campus-locator-dev-db`; `ec2 describe-security-group-rules --filters Name=group-id,Values=<id de -rds>` | `PubliclyAccessible = false`; `AvailabilityZone = us-east-1a`; grupo de subredes `campus-locator-dev-db` con exactamente `privada-a` y `privada-b`; su único grupo de seguridad es `campus-locator-dev-rds`, y toda regla entrante de ese grupo es `5432/tcp` desde `-api` o `-worker` (ningún `CidrIpv4`, `CidrIpv6` ni `PrefixListId`) |
| C3b | `rds describe-db-parameters --db-parameter-group-name campus-locator-dev-pg17` (sin `--source`: en PostgreSQL 17, `1` es el valor por defecto y RDS lo lista como `system`) y `DBParameterGroups` de la instancia | `rds.force_ssl = 1`; la instancia usa solo `campus-locator-dev-pg17` con `ParameterApplyStatus = in-sync`. La conexión real con TLS se prueba desde la VPC en INF-1.3 (C5) |
| C4 | `Engine` y `EngineVersion` de `rds describe-db-instances` | `Engine = postgres` y versión 17.x con x ≥ 1 (comparación numérica: 17.10 es mayor que 17.9) |
| C5a | `secretsmanager get-secret-value` de `campus-locator/dev/db`, `campus-locator/dev/jwt` y `campus-locator/dev/admin-inicial`; analiza el JSON en memoria y nunca imprime valores | `db` tiene exactamente `host`, `port`, `dbname`, `username`, `password`, con `host` = `Endpoint.Address` de la instancia, `port` = el número `5432`, `dbname = campus_locator`, `username = campus_app` y `password` no vacío; `jwt` tiene solo `secret`, que decodifica en base64 a 64 bytes; `admin-inicial` tiene exactamente `correo = admin@campus.edu.co` y `password` no vacío |
| C5b | `s3api head-bucket`, `get-bucket-encryption`, `get-public-access-block`, `get-bucket-ownership-controls`, `get-bucket-versioning`, `get-bucket-cors`, `get-bucket-lifecycle-configuration`, `get-bucket-notification-configuration` y `get-bucket-policy` del bucket | `AES256`; los cuatro indicadores de *Block Public Access* en `true`; `BucketOwnerEnforced`; versionado nunca activado (sin `Status`); error `NoSuchCORSConfiguration`; una sola regla de ciclo de vida, activa, sobre todo el bucket, con `AbortIncompleteMultipartUpload.DaysAfterInitiation = 7` y sin `Expiration` ni transiciones; una única `QueueConfiguration` (ni *topics*, ni Lambda, ni EventBridge) con `s3:ObjectCreated:*`, `prefix = dataset/`, `suffix = .jpg` y el ARN de `ingesta`; la política tiene una declaración `Deny` de `s3:*` a `*` sobre el bucket y sus objetos con `aws:SecureTransport = false`, y ninguna `Allow` |
| C5c | `sqs get-queue-attributes --attribute-names All` de las cuatro colas | `ingesta` `VisibilityTimeout = 180` y `purga` `300`; ambas con `MessageRetentionPeriod = 345600`, `ReceiveMessageWaitTimeSeconds = 20` y `RedrivePolicy` con `maxReceiveCount = 5` hacia su DLQ; las DLQ con `MessageRetentionPeriod = 1209600` y sin `RedrivePolicy`; las cuatro con `SqsManagedSseEnabled = true`; la `Policy` de `ingesta` tiene una sola declaración, que concede solo `sqs:SendMessage` sobre la cola al servicio `s3.amazonaws.com` con `aws:SourceArn` = ARN del bucket y `aws:SourceAccount = 648617469176`; `purga` y las DLQ no tienen `Policy` |
| C5d | `rds describe-db-instances` | `DBInstanceClass = db.t4g.micro`, `StorageType = gp3`, `AllocatedStorage` ≥ 20, `MaxAllocatedStorage = 50`, `StorageEncrypted`, `MultiAZ = false`, `DeletionProtection`, `BackupRetentionPeriod = 7`, `PreferredBackupWindow = 07:00-07:30`, `PreferredMaintenanceWindow = sun:08:00-sun:09:00`, `AutoMinorVersionUpgrade`, `CopyTagsToSnapshot`, `DBName = campus_locator`, `MasterUsername = campus_app` y puerto 5432 (§3.5, §5.1, §5.10) |
| C6 | `TagList` de la instancia; `rds describe-db-parameter-groups` y `describe-db-subnet-groups` y `rds list-tags-for-resource` de sus ARN; `s3api get-bucket-tagging`; `sqs list-queue-tags` de las cuatro colas; `secretsmanager describe-secret` de los tres secretos | Los once recursos llevan las cuatro etiquetas de §5.1 (`Proyecto = campus-locator`, `Entorno = dev`, `GestionadoPor = terraform`, `Carpeta = INFRASTRUCTURA_TERRAFORM`); el grupo de parámetros es de la familia `postgres17` |

`--solo` admite los alias `C3` (C3a y C3b) y `C5` (C5a–C5d). C1 y C2 comparten la subida y la lectura de la cola: con
`--solo C2` también se sube `c1.jpg`, que sirve de control positivo.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

- **Objetos**: `dataset/validacion-<sello>/c1.jpg` (C1 o C2) y, si C2 está incluida, `dataset/validacion-<sello>/c2.png`
  y `thumbs/validacion-<sello>/c2.jpg`. Al terminar, siempre, se borran (`s3api delete-objects`). Al empezar (si C1 o C2
  están incluidas) se listan `dataset/validacion-` y `thumbs/validacion-` (`s3api list-objects-v2 --prefix …`) y se
  borran los restos de ejecuciones anteriores (ver el punto siguiente). Nada fuera de esos dos prefijos se toca.
- **Claves de prueba que el script puede borrar**: las de su propio `<sello>` y las de otro sello con más de 15 min de
  antigüedad (restos de una ejecución anterior). Las de un sello reciente (otra ejecución en curso, u otro validador
  que use `dataset/validacion-…`) y las que no tienen la forma `validacion-AAAAMMDD-HHMMSS/` no se tocan.
- **Antes de subir nada** (C1 o C2):
  - Desde INF-1.3, `ecs describe-services --cluster campus-locator-dev --services worker`: si `worker` tiene
    `desiredCount`, `runningCount` o `pendingCount` mayor que 0, C1 y C2 fallan sin subir (se llevaría los eventos de
    prueba y C2 podría pasar en falso). Si el clúster no existe (antes de INF-1.3), no hay nada que comprobar.
  - `sqs get-queue-attributes` de `ingesta`: con mensajes en proceso o retrasados, o más de 10 visibles, C1 y C2 fallan
    **sin leer la cola**. Con 1–10 visibles, los lee una vez (hasta que la cola queda vacía): borra el `s3:TestEvent`
    del bucket y los eventos de claves de prueba borrables; si queda algún mensaje ajeno, lo devuelve a la cola y C1 y
    C2 fallan sin subir. Así un mensaje real recibe como mucho **una** recepción por ejecución, y solo si la cola tiene
    pocos mensajes: con `maxReceiveCount = 5`, cinco ejecuciones lo mandarían a la DLQ.
  - El `s3:TestEvent` lo envía S3 al guardar la notificación, así que tras el `apply` de este lote queda uno en la cola.
    No es un dato, y si se dejara, cada lectura le sumaría una recepción hasta mandarlo a la DLQ (alarma de INF-3.1). Es
    la única excepción a «no borrar lo que no creó»; cómo lo trata el `worker` lo define
    `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.8.
- **Mientras espera los eventos** (C1 y C2), todo lo que recibe queda oculto 300 s
  (`sqs receive-message --visibility-timeout 300`): los eventos de claves de prueba borrables se borran en cuanto se
  ven (`sqs delete-message-batch`) y los mensajes ajenos que lleguen a la vez se devuelven a la cola
  (`sqs change-message-visibility-batch --visibility-timeout 0`) al terminar la última lectura.
- **Al terminar**, siempre: si se subió `c1.jpg` y su evento no llegó, lee la cola 20 s más para borrar los eventos de
  prueba que lleguen tarde y después devuelve los ajenos; y borra los objetos subidos.
- Con `--sin-limpieza` los objetos se quedan (los borra la primera ejecución que empiece pasados 15 min) y los mensajes
  ajenos vuelven solos a la cola a los 300 s.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con `secretsmanager:GetSecretValue` sobre los tres
secretos, escritura en `dataset/validacion-*` y `thumbs/validacion-*`, lectura y borrado en `ingesta` y
`ecs:DescribeServices`; para los pasos 5
y 6 de la preparación, sesión de `gh` de la cuenta dueña del repositorio, revisora del entorno `dev`. La región es
`us-east-1` (§5.3). Los comandos van desde la raíz del repositorio, con `export AWS_REGION=us-east-1`.

**Preparación** (una sola vez, al cerrar el lote). El validador comprueba los recursos **después** del `apply` desde
`main`: sin él termina con código 1 (`no existe la cola campus-locator-dev-ingesta`, `no existe la instancia …`).

1. Comprobar que ningún nombre del lote está ocupado (restos de un intento anterior, R11):
   ```bash
   aws s3api head-bucket --bucket campus-locator-dev-dataset-648617469176 2>&1 | tail -1
   aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
   aws rds describe-db-parameter-groups \
     --query "DBParameterGroups[?starts_with(DBParameterGroupName,'campus-locator')].DBParameterGroupName" --output text
   aws rds describe-db-subnet-groups \
     --query "DBSubnetGroups[?starts_with(DBSubnetGroupName,'campus-locator')].DBSubnetGroupName" --output text
   aws rds describe-db-snapshots --snapshot-type manual \
     --query "DBSnapshots[?starts_with(DBSnapshotIdentifier,'campus-locator-dev-db')].DBSnapshotIdentifier" --output text
   aws sqs list-queues --queue-name-prefix campus-locator --output text
   aws secretsmanager list-secrets --include-planned-deletion \
     --query "SecretList[?starts_with(Name,'campus-locator')].[Name,DeletedDate]" --output text
   ```
   Esperado: `head-bucket` termina en `Not Found` (404), los cinco siguientes no imprimen nada y el último solo lista
   `campus-locator-dev/jwt-secret` con fecha de borrado (otro nombre, no choca). Si aparece cualquiera de los nombres de
   §5.1 del lote o el *snapshot* `campus-locator-dev-db-final`, parar y revisarlo antes de seguir.
2. Añadir `hashicorp/random` al lock sin actualizar `aws` (`init` sin `-upgrade` solo instala lo que falta):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev init -input=false
   terraform -chdir=envs/dev providers lock -platform=linux_amd64 -platform=windows_amd64 \
     -platform=darwin_amd64 -platform=darwin_arm64
   grep -A1 '^provider' envs/dev/.terraform.lock.hcl
   ```
   Esperado: `registry.terraform.io/hashicorp/aws` con `version = "6.70.0"` y `registry.terraform.io/hashicorp/random`
   con una `3.x` (≥ 3.7). Si `aws` ya no es 6.70.0, parar: el cambio de proveedor va en su propio lote.
3. Comprobaciones locales y `plan`:
   ```bash
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|^  \+ (bucket_dataset|rds_endpoint|secretos|sqs_)'
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 24 to add, 0 to change, 0 to destroy.` y las
   siete líneas `+ bucket_dataset`, `+ rds_endpoint`, `+ secretos`, `+ sqs_ingesta_dlq_url`, `+ sqs_ingesta_url`,
   `+ sqs_purga_dlq_url` y `+ sqs_purga_url`. Ningún valor de secreto aparece en el `plan` (salen como `(sensitive
   value)`). Un *push* directo a `main` no tiene `plan` en un PR (§3.9): este es el que revisa quien aprueba el paso 5.
4. Commit y *push* a `main` de los módulos, `envs/dev` (con el lock), el validador y `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/datos INFRASTRUCTURA_TERRAFORM/project/modules/secretos \
     INFRASTRUCTURA_TERRAFORM/project/envs/dev INFRASTRUCTURA_TERRAFORM/project/src/ops/validate12.py \
     INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-1.2: datos y secretos"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/` ni `.validacion/`. En GitHub arranca `infra.yml`
   y su job `apply (main)` queda esperando la aprobación del entorno `dev`.
5. Aprobar el `apply`: igual que el paso 4 de [`validation-1-1`](./validation-1-1.md) §5, con `comment="INF-1.2"`.
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 24 added, 0 changed, 0 destroyed.`
   Crear la instancia de RDS tarda 5–15 min. Si falla solo la notificación con `Unable to validate the following
   destination configurations` (la política de la cola aún no se había propagado), se repite el job con
   `gh run rerun "$RUN" --failed` y se aprueba de nuevo: el resto ya está creado y el `plan` solo tendrá la
   notificación.
6. Comprobar que no quedan diferencias (un atributo que AWS normaliza distinto daría cambios en cada `plan`):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -detailed-exitcode -no-color | tail -1
   echo "codigo=${PIPESTATUS[0]}"
   ```
   Esperado: `No changes. Your infrastructure matches the configuration.` y `codigo=0`.

Este lote no añade variables al repositorio de GitHub (§5.9).

**Ejecución:**

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate12.py --entorno dev
```

Esperado: `[PASA]` en P2, P1, C1, C2, C3a, C3b, C4, C5a, C5b, C5c, C5d y C6 y `Resultado: pasa (código 0)`. Duración
aproximada: 1–2 min (casi todo es la espera del evento de C1 y los 30 s de C2).
