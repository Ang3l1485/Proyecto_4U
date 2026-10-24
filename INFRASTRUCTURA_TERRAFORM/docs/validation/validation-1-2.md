# Validación 1-2 — INF-1.2 Datos y secretos

| Campo | Valor |
|---|---|
| Lote | `INF-1.2` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate12.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P2 es de credenciales: código 3,
según §5.11).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.1` en «Hecho»: subredes privadas y grupos que usa RDS | `ec2 describe-subnets --filters Name=tag:Name,Values=campus-locator-dev-privada-a,campus-locator-dev-privada-b` devuelve dos y `ec2 describe-security-groups --filters Name=group-name,Values=campus-locator-dev-rds,campus-locator-dev-api,campus-locator-dev-worker` devuelve tres |
| P2 | Credenciales de la cuenta `648617469176`, con lectura de secretos | `aws sts get-caller-identity` devuelve `Account = 648617469176`; `secretsmanager list-secrets` no da `AccessDenied` |

Los recursos se localizan por nombre (§5.1): bucket `campus-locator-dev-dataset-648617469176`, colas con
`sqs get-queue-url --queue-name …`, instancia `campus-locator-dev-db` y secretos `campus-locator/dev/…`. Los outputs de
§5.2 se exigen en INF-1.3 (C4).

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Sube con `s3api put-object` un JPEG mínimo generado en memoria a `dataset/validacion-<AAAAMMDD-HHMMSS>/c1.jpg`; lee `campus-locator-dev-ingesta` con `sqs receive-message --wait-time-seconds 20 --max-number-of-messages 10 --visibility-timeout 30` durante 90 s como máximo | Llega un mensaje con `Records[0].eventName` que empieza por `ObjectCreated:`, `s3.bucket.name` = el bucket y `s3.object.key` (decodificada con `unquote_plus`) = la clave subida |
| C2 | Antes de subir el objeto de C1, sube `dataset/validacion-<AAAAMMDD-HHMMSS>/c2.png` y `thumbs/validacion-<AAAAMMDD-HHMMSS>/c2.jpg`; revisa todo mensaje recibido mientras espera el de C1 y durante 30 s más | Ningún mensaje menciona `…/c2.png` ni `thumbs/validacion-<AAAAMMDD-HHMMSS>/c2.jpg` |
| C3a | `rds describe-db-instances --db-instance-identifier campus-locator-dev-db`; `ec2 describe-security-group-rules` de los grupos que tiene asignados | `PubliclyAccessible = false`; `AvailabilityZone = us-east-1a`; el grupo de subredes solo contiene `privada-a` y `privada-b`; su único grupo es `campus-locator-dev-rds` y sus reglas entrantes solo referencian a `-api` y `-worker` (ningún `CidrIpv4` ni `CidrIpv6`) |
| C3b | `rds describe-db-parameters --db-parameter-group-name campus-locator-dev-pg17 --source user` y `DBParameterGroups` de la instancia | `rds.force_ssl = 1`; la instancia usa `campus-locator-dev-pg17` con `ParameterApplyStatus = in-sync`. La conexión real con TLS se prueba desde la VPC en INF-1.3 (C5) |
| C4 | `Engine` y `EngineVersion` de `rds describe-db-instances` | `Engine = postgres` y versión 17.x con menor ≥ 1 (comparación numérica, no de texto) |
| C5a | `secretsmanager get-secret-value` de `campus-locator/dev/db`, `campus-locator/dev/jwt` y `campus-locator/dev/admin-inicial`; analiza el JSON en memoria y nunca imprime valores | `db` tiene `host`, `port`, `dbname`, `username`, `password`, con `host` = `Endpoint.Address` de la instancia, `port = 5432`, `dbname = campus_locator` y `username = campus_app`; `jwt.secret` decodifica en base64 a 64 bytes; `admin-inicial` tiene `correo = admin@campus.edu.co` y `password` no vacío |
| C5b | `s3api get-bucket-encryption`, `get-public-access-block`, `get-bucket-ownership-controls`, `get-bucket-versioning`, `get-bucket-cors`, `get-bucket-lifecycle-configuration` y `get-bucket-notification-configuration` del bucket | `AES256`; los cuatro indicadores de *Block Public Access* en `true`; `BucketOwnerEnforced`; sin versionado; error `NoSuchCORSConfiguration`; una regla con `AbortIncompleteMultipartUpload.DaysAfterInitiation = 7` y sin `Expiration`; una única `QueueConfiguration` con `s3:ObjectCreated:*`, `prefix = dataset/`, `suffix = .jpg` y el ARN de `ingesta` |
| C5c | `sqs get-queue-attributes --attribute-names All` de las cuatro colas | `ingesta` `VisibilityTimeout = 180` y `purga` `300`; ambas con `MessageRetentionPeriod = 345600`, `ReceiveMessageWaitTimeSeconds = 20` y `RedrivePolicy` con `maxReceiveCount = 5` hacia su DLQ; las DLQ con `MessageRetentionPeriod = 1209600`; las cuatro con `SqsManagedSseEnabled = true`; la `Policy` de `ingesta` solo concede `sqs:SendMessage` a `s3.amazonaws.com` con `aws:SourceArn` = ARN del bucket y `aws:SourceAccount = 648617469176` |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea tres objetos: `dataset/validacion-<AAAAMMDD-HHMMSS>/c1.jpg`, `dataset/validacion-<AAAAMMDD-HHMMSS>/c2.png` y
`thumbs/validacion-<AAAAMMDD-HHMMSS>/c2.jpg`. Borra el mensaje de C1 (`sqs delete-message`) en cuanto lo valida; los
mensajes ajenos que reciba (incluido el `s3:TestEvent` de la notificación) vuelven a la cola sin tocarse
(`sqs change-message-visibility --visibility-timeout 0`). Al terminar, siempre, borra los tres objetos
(`s3api delete-objects`) y consume y borra los mensajes de `ingesta` cuya clave empiece por `dataset/validacion-`. Al
empezar, lista `dataset/validacion-` y `thumbs/validacion-` (`s3api list-objects-v2 --prefix …`) y borra los restos de
ejecuciones anteriores; sus mensajes se borran en cuanto aparecen al leer la cola.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate12.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con `secretsmanager:GetSecretValue` sobre los tres
secretos. La región es `us-east-1` (§5.3). Si `worker` ya consume `ingesta` (INF-1.3 en adelante), ejecútese fuera
del horario de INF-2.1 para que no se lleve el mensaje de C1. Duración aproximada: 2–4 min.
