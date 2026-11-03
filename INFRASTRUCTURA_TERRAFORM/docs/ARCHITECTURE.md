# ARCHITECTURE — Infraestructura (`INFRASTRUCTURA_TERRAFORM`)

| Campo | Valor |
|---|---|
| Versión del documento | **0.15.1** (historia en [`CHANGELOG.md`](./CHANGELOG.md)) |
| Fecha | 2026-10-26 |
| Estado | Diseño propuesto. **INF-0.1 a INF-3.1 aplicados y validados** (bootstrap de la cuenta; esqueleto de `envs/dev` y CI de Terraform `infra.yml`; red y grupos de seguridad; datos y secretos; cómputo con la imagen de prueba; borde HTTPS; encendido de `embedding` y escalado del `worker`; observabilidad y alarmas, con la regla de 0.15.0 y la suscripción confirmada). INF-6.1, diferido |
| Nube | AWS, cuenta `648617469176`, región `us-east-1` |
| Entorno | `dev` (único por ahora) |
| Qué se construye y en qué orden | [`PLAN.md`](./PLAN.md) · cómo se comprueba cada lote: [`validation/`](./validation/) |

Este documento describe **la infraestructura de todo el sistema en AWS**: red, borde HTTPS, cómputo, datos, secretos,
permisos, observabilidad, CI/CD y costos. Su **§5 es la única fuente de verdad** de las interfaces que esta carpeta
expone: nombres de recursos, outputs de Terraform, variables de entorno y secretos que reciben los servicios, buckets,
colas, puertos, permisos IAM, contrato de despliegue y parámetros operativos.

---

## 1. Propósito y alcance

### 1.1 Qué cubre

- Toda la infraestructura de AWS que necesitan `BACKEND_FASTAPI` y `SERVICE_EMBEDDING` para funcionar.
- El estado remoto de Terraform, el acceso de GitHub Actions a AWS (OIDC) y el control de gasto.
- El contrato de despliegue que siguen los workflows de `.github/workflows/`.
- El contrato común de los validadores de lotes de las cuatro carpetas (§5.11).

### 1.2 Qué no cubre

- La lógica de cada servicio (está en el `docs/ARCHITECTURE.md` de cada carpeta).
- El mapa base: la app pide las teselas directamente a OpenStreetMap (ver `FRONTEND_KOTLIN/docs/ARCHITECTURE.md`, §2.6).
- La compilación y publicación de la app Android (no usa AWS).

### 1.3 Regla de contratos del monorepo

Cada carpeta define en **su** §5 solo lo que **expone**; las demás enlazan, nunca copian.

| Interfaz | Dueño (única fuente de verdad) |
|---|---|
| API REST pública y de administración, esquema de la base, formato de mensajes de las colas | `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5 |
| API interna de embeddings, modelo, preprocesamiento y formato del vector | `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5 |
| Nombres de recursos, outputs de Terraform, variables de entorno y secretos inyectados, buckets, colas y sus atributos, puertos, IAM, contrato de despliegue | **Este documento**, §5 |
| Puentes WebView, almacenamiento local de la app, contratos entre vistas | `FRONTEND_KOTLIN/docs/ARCHITECTURE.md` §5 |

Cómo se cambia una interfaz:
1. Se edita primero el §5 del dueño (y se sube la versión del documento).
2. Se añade la entrada correspondiente en el `CHANGELOG.md` de esa carpeta.
3. Después se cambia el código. Las carpetas que consumen la interfaz abren un lote en su `PLAN.md` si les afecta.

---

## 2. Vista general en AWS

```
                               Internet (HTTPS)
 App Android ─────────────────────────────────────────────┐
     │                                                    ▼
     │ PUT con URL prefirmada                API Gateway HTTP API   campus-locator-dev-api
     │ (fotos del dataset)                   (TLS de AWS, throttling, 30 s, 10 MB)
     ▼                                                    │ VPC Link
 S3  campus-locator-dev-dataset-648617469176              ▼
     │ evento ObjectCreated (dataset/*.jpg)   ┌─ VPC 10.20.0.0/16 ── cómputo en us-east-1a ───────────────┐
     ▼                                        │  Cloud Map  api.campus-locator.local (SRV :8000)          │
 SQS campus-locator-dev-ingesta ─────────────►│                                                           │
 SQS campus-locator-dev-purga   ─────────────►│  ECS Fargate (cluster campus-locator-dev)                 │
     ▲                                        │   ├─ api       FastAPI      ──HTTP──┐                     │
     └── la api encola purgas y re-procesados │   ├─ worker    ingesta y purga ─────┼─► embedding :8080   │
                                              │   └─ embedding DINOv2 ViT-S/14 (CPU)◄┘  (A record,        │
                                              │                                        Cloud Map)         │
                                              │        │                                                  │
                                              │        ▼  :5432 (subred privada)                          │
                                              │   RDS PostgreSQL 17 + pgvector   campus-locator-dev-db    │
                                              └───────────────────────────────────────────────────────────┘
 Transversal: Secrets Manager · CloudWatch Logs · CloudWatch Alarms y EventBridge → SNS campus-locator-dev-alertas
             (correo) · AWS Budgets (correo) · ECR
 Fuera de AWS: GitHub Actions (OIDC) despliega · la app pide teselas a OpenStreetMap
```

### 2.1 Flujos principales

| Flujo | Recorrido | Síncrono |
|---|---|---|
| **Ubicarse** (`POST /v1/localize`) | App → API Gateway → `api` → `embedding` (5 vectores) → RDS (búsqueda kNN) → `api` responde | Sí (objetivo: p95 ≤ 1 s en el servidor, con `embedding` encendido) |
| **Ingesta del dataset** | App pide URLs prefirmadas a `api` → sube cada JPEG a S3 → S3 publica el evento en `ingesta` → `worker` descarga, genera miniatura, pide el vector a `embedding` y lo guarda en RDS | No |
| **Borrado de un video** | App → `api` (borrado lógico + saca los vectores de la búsqueda en la misma transacción) → `api` encola en `purga` → `worker` borra objetos de S3 y filas | Parcial |
| **Despliegue** | `git push` a `main` → GitHub Actions (OIDC) → ECR → tarea `migrate` → nueva revisión de la tarea → `ecs update-service` | — |

Detalle funcional de cada flujo: `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §4.

---

## 3. Arquitectura en AWS

### 3.1 Cuenta, región y entornos

- Una sola cuenta (`648617469176`) y una sola región (`us-east-1`), elegida por precio y catálogo de servicios.
- Un único entorno, `dev`. Un futuro `prod` reutiliza los mismos módulos con otro `envs/prod/` (Fase 6 del PLAN).
- Todos los recursos llevan las etiquetas de §5.1; el proveedor de Terraform fija `allowed_account_ids` para que
  un `apply` con credenciales de otra cuenta falle.
- Higiene de la cuenta (fuera de Terraform, se hace a mano una vez): MFA en el usuario raíz y sin llaves de acceso
  para él; un usuario administrador con MFA para el `bootstrap`; *S3 Block Public Access* activado a nivel de cuenta.
- Roles vinculados a servicios creados a mano (fuera de Terraform; se crean una vez por cuenta y nada los borra):
  `AWSServiceRoleForAPIGateway` (lo necesita el VPC Link de INF-1.4). Lo creó `root` el 2026-10-24 a las 23:16 UTC,
  antes del `apply` de INF-1.4 (CloudTrail, `CreateServiceLinkedRole`); el `apply` lo intentó crear a las 23:22 y
  recibió `InvalidInputException` porque ya existía. Si falta en otra cuenta: `aws iam create-service-linked-role
  --aws-service-name ops.apigateway.amazonaws.com`. `AWSServiceRoleForApplicationAutoScaling_ECSService` (lo usan los
  objetivos escalables de INF-2.1) no existía: se creó igual, con `--aws-service-name
  ecs.application-autoscaling.amazonaws.com`, el 2026-10-24 antes del `apply` de INF-2.1 (`validation-2-1` §5, paso 1).

### 3.2 Red

- VPC `10.20.0.0/16` con DNS habilitado.
- Cuatro subredes en dos zonas. **El cómputo y la base de datos viven solo en `us-east-1a`**; las subredes de
  `us-east-1b` existen porque el grupo de subredes de RDS exige al menos dos zonas (ADR-INF-03).
- **Sin NAT Gateway** (ADR-INF-02). Las tareas de Fargate corren en las subredes públicas con IP pública para llegar
  a ECR, S3, SQS, Secrets Manager y CloudWatch por el Internet Gateway. Ningún grupo de seguridad de tareas admite
  tráfico entrante desde internet.
- RDS vive en las subredes privadas (sin ruta a internet y sin IP pública).
- *Gateway endpoint* de S3 (gratuito) asociado a la tabla de rutas pública: el tráfico a S3 no sale por internet.
- Dos tablas de rutas propias: `-publica` (ruta `local`, `0.0.0.0/0` → Internet Gateway y la del endpoint de S3) para
  las dos subredes públicas y `-privada` (solo `local`) para las dos privadas. La tabla principal de la VPC no la usa
  ninguna subred.
- Las subredes no asignan IP pública por sí solas (`map_public_ip_on_launch = false`): la IP pública de cada tarea la
  pide ECS con `assignPublicIp = ENABLED` (INF-1.3 y el `run-task` de §5.9).
- El grupo `default` de la VPC queda **sin reglas** (Terraform lo adopta con `aws_default_security_group`): lo que se
  cree sin un grupo explícito no tiene tráfico, en vez de quedar abierto entre sí (§5.7).

### 3.3 Borde HTTPS: API Gateway HTTP API + VPC Link + Cloud Map

- La app habla con una **HTTP API** de API Gateway, que da HTTPS con certificado de AWS sin dominio propio
  (`https://<id>.execute-api.us-east-1.amazonaws.com`). Android bloquea HTTP en claro por defecto, así que esto evita
  comprar un dominio en `dev` (ADR-INF-04).
- Dos rutas con la misma integración privada `HTTP_PROXY` por **VPC Link** hacia el servicio de **Cloud Map** `api`:
  `ANY /{proxy+}` y `POST /v1/auth/login`. La segunda existe solo para tener su propio *throttling*, porque en una
  HTTP API los límites se fijan por ruta. API Gateway solo sabe leer registros **SRV** de Cloud Map, por eso el servicio
  ECS `api` se
  registra con SRV (IP + puerto 8000).
- Etapa `$default` con despliegue automático. *Throttling* por ruta (§5.10): la cuota general en `ANY /{proxy+}` y
  otra más estricta en `POST /v1/auth/login`.
- El *throttling* es aproximado: AWS lo aplica «best effort» y reparte el límite entre sus nodos, así que un solo
  cliente pasa bastante más de lo configurado. Medido el 2026-10-24 contra login (2 req/s, ráfaga 5) desde una sola
  máquina: a 5 req/s, 1 de 100 recibió 429; a 10, 20 y 50 req/s, el 23 %, el 34 % y el 57 % (pasaron ~8, ~13 y ~21
  req/s). Sirve para frenar abusos de volumen (R10), **no** como límite de intentos de inicio de sesión: ese lo tendría
  que poner el backend.
- Límites que heredan los servicios: **30 s** de tiempo máximo de integración y **10 MB** de carga útil por petición.
  Por eso las fotos del dataset no pasan por la API (van directo a S3 con URL prefirmada). Las respuestas que genera
  la propia API Gateway (500 sin instancias de `api`, 429, 413) y lo que recibe `api` están en §5.13.
- La autenticación **no** se valida en API Gateway: el JWT es propio (HS256) y lo verifica FastAPI
  (`BACKEND_FASTAPI/docs/ARCHITECTURE.md`, ADR-BE-03).
- *Access logs* de la API a CloudWatch, en el *log group* `/campus-locator/dev/apigw` (lo crea `borde`, 14 días), con
  el formato JSON de §5.10.
- El VPC Link `campus-locator-dev-vpclink` vive en las dos subredes públicas (API Gateway pide subredes de al menos dos
  zonas) con el grupo `-vpclink`, que solo sale a `8000/tcp` hacia `-api` (§5.7).
- La API tiene `prevent_destroy` (R8): un `plan` que la recree falla en vez de cambiar la URL de la app.

### 3.4 Cómputo: ECS sobre Fargate

Un clúster `campus-locator-dev` con tres servicios y dos tareas sueltas, todo en Fargate. Todas las tareas son
`X86_64` / Linux (ADR-INF-14) y usan `awsvpc`.

| Servicio / tarea | Imagen | Proceso | Tamaño | Réplicas | Descubrimiento |
|---|---|---|---|---|---|
| `api` | `campus-locator/backend` | servidor HTTP (FastAPI) en `:8000` | 0,25 vCPU / 0,5 GB | 1 fija | Cloud Map SRV `api.campus-locator.local` |
| `worker` | `campus-locator/backend` (otro comando) | consumidor de `ingesta` y `purga` | 0,25 vCPU / 0,5 GB | 0–1 según la cola, solo con `embedding` encendido | ninguno |
| `embedding` | `campus-locator/embedding` | DINOv2 ViT-S/14 en CPU en `:8080` | 2 vCPU / 4 GB | 0 por defecto; 1 al encenderlo a mano | Cloud Map A `embedding.campus-locator.local` |
| `migrate` (tarea suelta) | `campus-locator/backend` (otro comando) | migraciones Alembic + admin inicial | 0,25 vCPU / 0,5 GB | la lanza CI con `run-task` | ninguno |
| `validacion` (tarea suelta) | pública `postgres:17-alpine` | `psql` y `nslookup` para los validadores (§5.11) | 0,25 vCPU / 0,5 GB | la lanzan los validadores con `run-task` | ninguno |

- Los comandos exactos de cada proceso los define `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.9 y
  `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5.5; esta carpeta solo los referencia en la definición de tarea.
- **Encendido y apagado de `embedding`** (ADR-INF-11, ADR-INF-14, ADR-INF-15): apagado por defecto. Se enciende a mano
  antes de probar con `src/ops/embedding.py encender` (3–6 min hasta sano: 1–3 esperando a que la alarma de
  inactividad vea el encendido y 2–3 de arranque) y se apaga con `embedding.py apagar` o solo: tras 45 min sin
  peticiones a `POST /v1/localize` ni mensajes visibles o en vuelo en `ingesta` o `purga` (alarma
  `campus-locator-dev-embedding-inactivo`, que lee el filtro de métricas de los *access logs* y las métricas de SQS), y
  a las 22:00 (hora de Bogotá). Poner `desiredCount = 1` con `ecs update-service` no basta: si esa alarma está en
  `ALARM` (puede estarlo mientras nadie usa el sistema), su política lo devuelve a 0 en un minuto; el contrato de
  encendido está en §5.10. Con `embedding` apagado, `api` sigue respondiendo (`/v1/health`, login, lugares, alertas) pero
  `/v1/localize` devuelve `503 EMBEDDING_NO_DISPONIBLE`.
- **`worker` escala por cola**: sube a 1 con `ApproximateNumberOfMessagesVisible ≥ 1` en `ingesta` o `purga` **y**
  `embedding` encendido; 15 minutos sin mensajes visibles ni en vuelo → 0. `embedding.py apagar` y la acción de las 22:00
  también lo dejan en 0 (capacidad máxima 0 hasta el siguiente `embedding.py encender`), aunque queden mensajes. Con
  `embedding` apagado los mensajes esperan en la cola (retención de 4 días): la ingesta avanza cuando se enciende
  `embedding`. La condición «`embedding` encendido» va en la propia alarma de subida: mensajes visibles y una muestra
  de `CPUUtilization` del servicio `embedding` (ECS solo la publica con tareas en marcha) en el mismo minuto. Así,
  tras el apagado por inactividad, que no cambia el rango de `worker`, los mensajes nuevos tampoco lo suben.
- SQS y ECS publican sus métricas por minuto con unos minutos de retraso, y SQS hasta 15 min cuando una cola vuelve a
  tener actividad tras más de 6 h sin ella: la subida de `worker` puede tardar eso. Las alarmas rellenan con 0 los
  minutos sin dato (`FILL`), así que el apagado por inactividad puede llegar un minuto antes de los 45.
- *Health checks* de contenedor (§5.7) y *deployment circuit breaker* con *rollback* activado en los tres servicios.
- **ECS Exec** (`enable_execute_command`) solo en `api`, para depurar en `dev` (y para la comprobación de disco de
  BE-3.2). Quien lo use necesita el *Session Manager plugin* de la CLI de AWS. `worker` y `embedding` no lo tienen.
- **Terraform crea los servicios, CI cambia la imagen**: los servicios ignoran cambios en `task_definition` y
  `desired_count` (ADR-INF-09). El contrato de CI está en §5.9.

### 3.5 Datos

**RDS PostgreSQL** (`campus-locator-dev-db`)
- PostgreSQL **17** (≥ 17.1, la que trae pgvector 0.8.0 en RDS), `db.t4g.micro` (2 vCPU, 1 GiB), una sola zona
  (`us-east-1a`), 20 GB `gp3` cifrados (clave de AWS de RDS) con autoescalado de almacenamiento hasta 50 GB.
- Terraform fija solo la versión mayor (`engine_version = "17"`): RDS crea la instancia con la menor por defecto y la
  actualiza sola (`auto_minor_version_upgrade`) en la ventana de mantenimiento (§5.10). Cambiar de mayor no es
  automático (`allow_major_version_upgrade = false`).
- Sin acceso público; solo admite `:5432` desde los grupos de seguridad de `api` y `worker` (`migrate` y la tarea de
  validación usan el de `api`, §5.7). Vive en el grupo de subredes `campus-locator-dev-db` (las dos privadas).
- Copias automáticas 7 días; *snapshot* final `campus-locator-dev-db-final` al destruir (si ya existe uno de una
  destrucción anterior, hay que borrarlo antes); `deletion_protection` activado. En `dev` los cambios se aplican con
  el `apply` (`apply_immediately`), sin esperar a la ventana.
- La extensión `vector` la crea la primera migración del backend (`CREATE EXTENSION IF NOT EXISTS vector`).
  Terraform no crea tablas.
- Grupo de parámetros propio (§5.10) con `rds.force_ssl = 1`.

**S3** (`campus-locator-dev-dataset-648617469176`)
- Privado, cifrado SSE-S3, *Block Public Access*, propiedad de objetos `BucketOwnerEnforced`, sin versionado, y una
  política que rechaza toda petición sin TLS (§5.5).
- Prefijos y notificación hacia SQS en §5.5. Las fotos de `/v1/localize` **nunca** se escriben aquí: se procesan en
  memoria y se descartan (`BACKEND_FASTAPI/docs/ARCHITECTURE.md`, ADR-BE-06).

**SQS**
- `ingesta`: recibe directamente las notificaciones `ObjectCreated` de S3. DLQ tras 5 recepciones. Al guardar la
  notificación, S3 deja en la cola un `s3:TestEvent` (§5.6).
- `purga`: la llena la `api` al borrar un video. DLQ tras 5 recepciones.
- Atributos en §5.6. El formato de los mensajes lo define el backend (§5.8 de su documento).

### 3.6 Secretos y configuración

- Tres secretos en Secrets Manager (§5.4). ECS los inyecta como variables de entorno al arrancar cada tarea.
- La contraseña de la base la genera Terraform (`random_password`) y la guarda en el secreto `db`; no hay rotación
  automática en `dev` (ADR-INF-07). Consecuencia: el valor queda en el estado de Terraform, que está cifrado y es
  privado (§3.9).
- Los secretos usan la clave gestionada `aws/secretsmanager` y, si se borran, quedan 7 días recuperables (el mínimo):
  mientras tanto su nombre no se puede volver a crear. Para recrearlos antes, se restauran
  (`aws secretsmanager restore-secret --secret-id <nombre>`) y se importan al estado
  (`terraform import 'module.secretos.aws_secretsmanager_secret.secretos["<clave>"]' <ARN>`).
- La configuración no secreta va como variables de entorno en texto plano en la definición de tarea (§5.4).

### 3.7 Identidad y permisos

- Un **rol de ejecución** común (descargar de ECR, escribir logs, leer los tres secretos).
- Un **rol de tarea** por proceso con el mínimo necesario (§5.8). `embedding` no tiene permisos sobre ningún servicio
  de AWS.
- Tres roles para GitHub Actions por **OIDC** (sin llaves de larga duración): uno de solo lectura para el `plan` de los
  PR, otro para aplicar Terraform y otro para desplegar imágenes. El *trust policy* solo acepta el repositorio y las
  ramas/entornos indicados en §5.8.
- Todo rol que crea Terraform desde `envs/dev` lleva el *permissions boundary* `campus-locator-limite-roles` (§5.8,
  ADR-INF-12): ningún rol nuevo puede tener más permisos que el propio `apply` ni tocar IAM.

### 3.8 Observabilidad y alertas

- Un *log group* por proceso, retención 14 días (§5.10). Los cinco de los procesos (`api`, `worker`, `embedding`,
  `migrate`, `validacion`) los crea `computo` (INF-1.3), porque las tareas no arrancan sin ellos; el de la API, `borde`
  (INF-1.4).
- Alarmas de CloudWatch publicadas en el topic SNS `campus-locator-dev-alertas` (suscripción por correo, variable
  `correo_alertas`; SNS envía un correo de confirmación y no entrega nada hasta que se confirma): errores 5xx de la API,
  mensajes en cualquier DLQ, `embedding` encendido demasiadas horas seguidas (el apagado automático falló),
  almacenamiento libre y créditos de CPU de RDS (umbrales y parámetros exactos en §5.10). Las cuatro alarmas de
  escalado de INF-2.1 (§5.1) no avisan: su única acción es una política de Application Auto Scaling.
- Cada alarma de INF-3.1 avisa **solo al pasar a `ALARM`** (un correo por paso; sin aviso al volver a `OK`) y trata la
  falta de datos como «no incumple» (`notBreaching`): una DLQ vacía e inactiva, una API sin peticiones o `embedding`
  apagado no publican su métrica y la alarma queda en `OK`. El correo de CloudWatch trae en el asunto `ALARM:` y el
  nombre de la alarma, y en el cuerpo su descripción, que dice qué revisar.
- Una regla de **EventBridge** sobre los eventos `ECS Task State Change` avisa al mismo topic cuando una tarea de los
  **servicios** `api`, `worker` o `embedding` se detiene por error: `lastStatus = STOPPED`, `stopCode` =
  `EssentialContainerExited` o `TaskFailedToStart`, y `group` = `service:api`, `service:worker` o
  `service:embedding`, solo del clúster `campus-locator-dev` (la cuenta tiene otros proyectos). Desde 0.15.0 avisa
  también, por una segunda rama (`$or`), de la tarea de prueba de `validate31.py` (`startedBy = validacion-3-1`; ninguna
  otra tarea lleva ese `startedBy`), porque una tarea suelta no puede llevar `group = service:…` (trampa abajo). Las
  demás tareas sueltas (`migrate`, `validacion` y las que lanzan los validadores con la definición de `embedding`) tienen
  otro `group` (`family:<familia>`) y otro `startedBy` y no avisan, aunque salgan con 0 (`EssentialContainerExited`);
  su resultado lo lee quien las lanzó. Apagar un servicio (a mano, por inactividad o
  a las 22:00) da `stopCode = ServiceSchedulerInitiated` y tampoco avisa (las tareas viejas que detiene un despliegue,
  igual; sin comprobar). El correo
  («AWS Notification Message») lleva el **evento completo en JSON**, sin transformar: `group`, `startedBy`,
  `stopCode`, `stoppedReason`, `taskArn` y cada contenedor con su `exitCode` y `reason`.
  No se activa *Container Insights* (tiene costo y no hace falta para estas alertas).
- El topic tiene una política propia (§5.6): la declaración por defecto de AWS (la cuenta lo administra), más
  `cloudwatch.amazonaws.com` (alarmas de la cuenta) y `events.amazonaws.com` (solo la regla de arriba) como
  publicadores. **No se cifra**: con la clave gestionada `aws/sns`, CloudWatch y EventBridge no pueden publicar, y una
  clave propia de KMS cuesta 1 USD/mes (ADR-INF-16).
- Estado de lo de INF-3.1: aplicado el 2026-10-26 por `infra.yml` (ejecución 40377985054, `Apply complete!
  Resources: 11 added, 0 changed, 0 destroyed.`) y suscripción confirmada desde el correo. `validate31.py --entorno
  dev` sobre `8c98f90` (código 1): **comprobado** que las 6 alarmas, la regla, su destino, la política del topic y la
  suscripción quedaron como en §5.6 y §5.10 (C1a–C1c) y que una DLQ con un mensaje pasa su alarma a `ALARM` y SNS
  entrega el aviso (C2a: `ingesta-dlq` a los 2,7 min, 1 entregada, 0 fallidas; la historia de la alarma trae la
  entrada `Action` del aviso al topic, así que CloudWatch puede publicar con la política). Falló C3: ECS rechazó
  la tarea de prueba con `group = service:worker` (abajo). 0.15.0 (commit `91bac0a`) cambió la regla (rama
  `startedBy`, §5.10) y la tarea de prueba (sin `group`): aplicado por `infra.yml` (ejecución 40414967226,
  `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`). `validate31.py --entorno dev` sobre `91bac0a`
  (2026-10-26 22:47–22:54 UTC, código 0): **comprobado todo el camino** — `TestEventPattern` da lo esperado en los 9
  casos de C1b; la tarea de prueba se detuvo con `EssentialContainerExited` (código 3) a los 1,3 min; la regla
  registró 1 evento coincidente y 1 invocación sin fallos, y SNS entregó el aviso (C3b: EventBridge publica con la
  condición `aws:SourceArn` de la política); C2a repitió `ingesta-dlq` → `ALARM` a los 2,7 min con 1 entrega. Llegaron
  los dos correos (C2b con captura, C3c confirmado por el usuario; `validation-3-1` §3).
- Trampas conocidas:
  - La alarma de 5xx cuenta también los 500 que da API Gateway con `api` en 0 réplicas (§5.13; p. ej., durante un
    validador de INF-1.x) y los `503 EMBEDDING_NO_DISPONIBLE` de `/v1/localize` con `embedding` apagado: más de 5 en
    5 min mandan un correo aunque no haya un fallo del código.
  - La alarma de `embedding` encendido mira horas de reloj: avisa cuando hubo tareas de `embedding` en marcha en cada
    una de las últimas 10 horas (entre ~9 y 10 h de uso seguido, o un rato en cada hora). Un día de campo largo con
    `embedding` encendido más de ~9 h la dispara: es lo esperado.
  - Cualquiera que reciba un aviso puede darse de baja con el enlace del pie del correo: la suscripción desaparece y
    el siguiente `plan` la vuelve a crear (y hay que confirmarla otra vez). `validate31.py` C1c lo detecta.
  - Sin comprobar: que una tarea reemplazada por *health checks* fallidos llegue con `EssentialContainerExited` (si
    llegara con `ServiceSchedulerInitiated`, no avisaría); que EventBridge entregue un evento más de una vez (sería un
    correo repetido); y que SQS deje de publicar la métrica de una DLQ con mensajes pero sin actividad tras 6 h (la
    alarma volvería a `OK` sin avisar; el aviso ya se mandó al pasar a `ALARM`).
  - **Una tarea suelta no puede llevar `group = service:<nombre>`.** `run-task --group service:worker` da
    `InvalidParameterException` «Invalid namespace for group.» (comprobado el 2026-10-26 a las 22:17:05 UTC en
    CloudTrail, `RunTask` de `validate31.py`): el espacio `service:` es de los servicios (la documentación de ECS solo
    dice que el grupo de una tarea de servicio es su nombre y no se puede cambiar). Así, una tarea suelta nunca casa
    con la rama `group` de la regla: por eso existe la rama `startedBy = validacion-3-1` (0.15.0), y la rama de los
    servicios se prueba con `events:TestEventPattern` contra eventos sintéticos (`validate31.py` C1b).
  - Comprobado el 2026-10-26: EventBridge publica con la condición `ArnEquals aws:SourceArn` de la política del topic
    (C3b, 0 `FailedInvocations`) y CloudWatch también, con entrada `Action` en la historia de la alarma
    (`accion_publicada` busca «fail» o el nombre del topic; sin ninguna entrada, C2a decide con las métricas de SNS y lo
    dice en el detalle). Sigue sin verse el texto exacto de una acción fallida.
  - El correo de CloudWatch, tal como llegó (captura en `validation-3-1` §3): remitente «AWS Notifications»
    `no-reply@sns.amazonaws.com`, asunto `ALARM: "campus-locator-dev-ingesta-dlq" in US East (N. Virginia)`, con
    «State Change: OK -> ALARM», el motivo (`Threshold Crossed: 1 out of the last 1 datapoints [1.0 (…)]`) y la hora en
    UTC.
- **AWS Budgets** `campus-locator-mensual`: 100 USD/mes con avisos al 50 % y 80 % del gasto real y al 100 % del
  pronosticado, al mismo correo. Budgets escribe directamente a ese correo (suscriptor `EMAIL`), sin confirmación.
  *Cost Anomaly Detection* activado (sin costo).

### 3.9 Estado de Terraform y CI/CD

- **`project/bootstrap/`** se aplica **una sola vez** con el usuario administrador: crea el bucket de estado
  `campus-locator-tfstate-648617469176` (versionado, cifrado, privado), el proveedor OIDC de GitHub, los tres roles de
  GitHub Actions, el *permissions boundary* `campus-locator-limite-roles` y el presupuesto. Se aplica primero con
  estado local y luego se migra su propio estado al bucket (`terraform init -migrate-state`). Las variables del
  repositorio (§5.9) y el entorno `dev` de GitHub los crea `bootstrap/configurar_github.py` con `gh`; en un
  repositorio personal solo puede hacerlo su dueño.
- **`project/envs/dev/`** usa *backend* S3 con **bloqueo nativo** (`use_lockfile = true`, Terraform ≥ 1.10), sin
  DynamoDB (ADR-INF-08), y con `allowed_account_ids`: `init` falla con credenciales de otra cuenta. Su
  `.terraform.lock.hcl` se versiona y CI lo usa con `init -lockfile=readonly`.
- Workflows en `.github/workflows/` (raíz del monorepo). Solo se disparan con cambios en `project/` (y cada uno, además,
  con cambios en su propio archivo): editar `docs/` no despliega nada.
- **`infra.yml`** (INF-0.2): Terraform fijado en `TF_VERSION` (la misma versión que usa el equipo en local, hoy
  1.16.6, para que `fmt -check` y `plan` den lo mismo en local y en CI); TFLint con
  `project/.tflint.hcl` (preset `recommended` y *ruleset* de AWS) en todos los directorios de `project/`; acciones de
  terceros fijadas por SHA; `GITHUB_TOKEN` sin permisos salvo los de cada job. Un PR desde un *fork* no ejecuta el
  `plan` (no recibe token OIDC). El `plan` de un PR es un solo comentario que se actualiza en cada ejecución; un `plan`
  nuevo del mismo PR cancela el anterior, y los `apply` de `main` van en fila sin interrumpirse (si se acumulan varios
  pendientes, GitHub deja solo el más reciente, que aplica el árbol completo de `main`). Una ejecución de `main` que
  espera aprobación retiene la fila: la siguiente queda en cola, sin pedir aprobación, hasta que aquella se apruebe o se
  cancele (cancelarla no toca AWS). En `main`, el job
  `apply (main)` hace `plan` y `apply` de ese mismo plan tras la aprobación; quien aprueba revisa antes el `plan` del
  PR (un *push* directo a `main` no tiene `plan` previo).
- **Entorno `dev` de GitHub** (se crea en INF-0.1): *required reviewers* (aprobación manual) y *deployment branches*
  limitado a `main`. Así, un job de un PR que declare `environment: dev` no llega a arrancar y nunca obtiene un token
  con `sub = …:environment:dev`.

| Workflow | Disparador | Qué hace |
|---|---|---|
| `infra.yml` | cambios en `INFRASTRUCTURA_TERRAFORM/project/**` o en `infra.yml` | En PR, job `plan (PR)` (rol `gha-terraform-plan`): `fmt -check`, `tflint`, `validate`, `plan` (comentado en el PR). En `main`, job `apply (main)` (rol `gha-terraform`): `plan` + `apply`, con aprobación manual del entorno de GitHub `dev` |
| `backend.yml` | cambios en `BACKEND_FASTAPI/project/**` | En PR: lint y pruebas. En `main`: imagen → ECR → `migrate` → `api` y `worker` (§5.9) |
| `embedding.yml` | cambios en `SERVICE_EMBEDDING/project/**` | En PR: lint y pruebas. En `main`: imagen → ECR → `embedding` (§5.9) |
| `frontend.yml` | cambios en `FRONTEND_KOTLIN/project/**` | Compila y corre pruebas unitarias. No toca AWS |

### 3.10 Costos estimados (`dev`, `us-east-1`, precios de lista)

Tarifas usadas: Fargate Linux/x86 0,04048 USD por vCPU·h y 0,004445 USD por GB·h; IPv4 pública 0,005 USD/h;
RDS `db.t4g.micro` 0,016 USD/h; mes de 730 h. Ninguna cifra cuenta con capa gratuita. Las dos columnas suponen 40 h
y 160 h de `embedding` encendido al mes (uso de prueba de 1–3 personas y uso intensivo).

| Concepto | Supuesto | USD/mes, `embedding` 40 h | USD/mes, `embedding` 160 h |
|---|---|---|---|
| `api` (0,25 vCPU / 0,5 GB) | siempre encendida | 9,0 | 9,0 |
| `embedding` (2 vCPU / 4 GB) | solo mientras está encendido | 4,0 | 15,8 |
| `worker` (0,25 vCPU / 0,5 GB) | solo con `embedding` encendido y mensajes en cola | 0,2 | 0,7 |
| IPv4 públicas | `api` siempre; `embedding`, `worker` y `migrate` mientras corren | 3,9 | 4,6 |
| RDS `db.t4g.micro` + 20 GB `gp3` | una zona | 14,0 | 14,0 |
| Secrets Manager | 3 secretos | 1,2 | 1,2 |
| CloudWatch (logs ~2 GB; las 4 alarmas de escalado de INF-2.1, con 16 métricas en sus expresiones; 2 métricas propias) | 0,50 USD por GB de logs, 0,10 por métrica de cada alarma y 0,30 por métrica propia al mes | 3,2 | 3,2 |
| Observabilidad (INF-3.1): 6 alarmas de una métrica, topic SNS con suscripción por correo, regla de EventBridge | alarmas: 6 × 0,10; SNS: los primeros 1 000 correos del mes gratis (después, 2 USD por 100 000) y el topic sin costo; EventBridge: los eventos de servicios de AWS en el bus por defecto y su entrega a SNS no se cobran | 0,6 | 0,6 |
| ECR (~10 GB entre versiones) | conservar 5 por repo | 1,0 | 1,0 |
| Cloud Map, API Gateway, S3, SQS, transferencia | tráfico de desarrollo | ~3,0 | ~3,0 |
| **Total aproximado** | | **≈ 40** | **≈ 53** |

Cargos que pueden aparecer y no están en la tabla: créditos de CPU de RDS (los `t4g` corren en modo *unlimited* y
cobran si la media de 24 h supera la línea base), almacenamiento de copias por encima del tamaño de la base, y
cualquier recurso creado a mano fuera de Terraform, y horas de `embedding` si el apagado automático falla (cada hora
encendida cuesta ~0,10 USD; R13). El presupuesto (§3.8) avisa antes de pasar de 100 USD; con `embedding` encendido
todo el mes se pasaría por poco (~110 USD).

Hasta 0.13.1 la fila de CloudWatch contaba ya las 6 alarmas de INF-3.1 («10 alarmas», 3,8 USD); desde 0.14.0 van en su
propia fila y el total no cambia. INF-3.1 añade **0,6 USD/mes**. Cada ejecución de `validate31.py` cuesta menos de
0,01 USD (una tarea de 0,25 vCPU durante ~1 min con IPv4 pública, unas decenas de lecturas de métricas y dos correos).

---

## 4. Componentes y funcionamiento (por lote)

Estructura de la carpeta:

```
INFRASTRUCTURA_TERRAFORM/
├── docs/
│   ├── ARCHITECTURE.md, PLAN.md, CHANGELOG.md
│   └── validation/              validation-<fase>-<n>.md: cómo se comprueba cada lote (§5.11)
└── project/                     todo el código
    ├── bootstrap/               Estado local → migrado al bucket. Bucket de estado, OIDC, roles de CI, boundary, presupuesto;
    │                            configurar_github.py (variables y entorno dev de GitHub)
    ├── envs/
    │   └── dev/                 backend.tf, providers.tf, main.tf, variables.tf, terraform.tfvars, outputs.tf,
    │                            .terraform.lock.hcl (versionado)
    ├── modules/                 cada módulo: main.tf, versions.tf (y variables.tf/outputs.tf cuando su lote los añade)
    │   ├── red/                 VPC, subredes, IGW, rutas, endpoint de S3, grupos de seguridad
    │   ├── datos/               RDS (+ grupo de parámetros), bucket del dataset, colas SQS, notificación S3→SQS
    │   ├── secretos/            random_password y los tres secretos
    │   ├── computo/             ECR, clúster, Cloud Map, log groups de los procesos, roles, definiciones de tarea (incluida la de validación), servicios;
    │   │                        escalado.tf: objetivos, políticas, alarmas y acciones programadas de Application Auto Scaling (INF-2.1)
    │   ├── borde/               HTTP API, VPC Link, integración con Cloud Map, rutas, throttling, access logs (y su log group), filtro de métricas de /v1/localize
    │   └── observabilidad/      topic SNS con su política y la suscripción por correo, las 6 alarmas, regla de EventBridge y su destino (INF-3.1)
    ├── pruebas/
    │   └── imagen-prueba/       Dockerfile, servidor.py y README.md (cómo publicarla) de la imagen `bootstrap` (§5.11)
    ├── src/
    │   └── ops/                 validate<fase><n>.py y comun.py: validadores de los lotes INF-x.y (§5.11); embedding.py (INF-2.1, §5.10)
    ├── tests/
    │   └── ops/                 pruebas locales de los validadores con un AWS falso (desde INF-3.1): falsos.py, test_validate31.py, test_comun.py (§5.11)
    ├── .tflint.hcl              configuración de TFLint para infra.yml
    └── pyproject.toml           dependencias de los validadores (grupo `ops`: boto3, httpx) y de sus pruebas (grupo `pruebas`: pytest)
```

`project/envs/dev/main.tf` solo compone módulos; ningún módulo llama a otro. Las dependencias entre módulos pasan por
variables y outputs (por ejemplo, `computo` recibe los ARN de los secretos y los IDs de los grupos de seguridad).

| Lote | Cómo funciona |
|---|---|
| **INF-0.1 Bootstrap** | Recursos que deben existir antes de cualquier `plan` remoto. El bucket de estado tiene `prevent_destroy` y solo admite TLS. El rol `gha-terraform-plan` (PR) solo puede leer, incluidos los secretos de `dev`, que ya están en el estado; el rol `gha-terraform` (aplicar, con aprobación) tiene permisos amplios pero acotados a la cuenta y región, y todo rol que crea lleva el *permissions boundary* `campus-locator-limite-roles`; el rol `gha-deploy` solo puede publicar imágenes, registrar definiciones de tarea, actualizar los servicios y lanzar `migrate` (§5.8). `bootstrap/configurar_github.py` crea con `gh` las variables del repositorio y el **entorno `dev` de GitHub**: aprobación manual y despliegue solo desde `main` (§3.9) |
| **INF-0.2 Esqueleto** | `envs/dev` con *backend*, proveedor (`default_tags`, `allowed_account_ids`) y los seis módulos, vacíos, ya compuestos en `main.tf`; `data "aws_caller_identity"` (output `cuenta_id`) obliga a configurar el proveedor sin recursos y `data "aws_default_tags"` deja en el estado las etiquetas efectivas. `infra.yml` con `plan` en PR y `apply` aprobado en `main` (§3.9). A partir de aquí todo cambio de infraestructura entra por PR |
| **INF-1.1 Red** | Módulo `red`: VPC, cuatro subredes (las /24 número 0, 1, 10 y 11 de `cidr_vpc`), Internet Gateway, tablas `-publica` y `-privada`, endpoint de S3 en la pública, los cinco grupos de seguridad de §5.7 y el `default` sin reglas. Los grupos se crean aquí (no en cada módulo) y sin reglas en línea: cada regla es un `aws_vpc_security_group_ingress_rule` o `egress_rule`, así las referencias cruzadas no generan ciclos. Entrega a `envs/dev` los IDs que usan INF-1.2 a INF-1.4 (§5.12) y crea los outputs `subredes_tareas` y `sg_migrate` |
| **INF-1.2 Datos y secretos** | Módulo `datos`: RDS en `us-east-1a` (grupo de subredes con las dos privadas y grupo de parámetros con `rds.force_ssl`); bucket con cifrado, *Block Public Access*, propiedad, ciclo de vida, política «solo TLS» y notificación a `ingesta` (la política de la cola autoriza solo a ese bucket); colas y DLQ. Módulo `secretos`: `random_password`, `random_bytes` y los tres secretos. Los dos módulos se usan entre sí a través de `envs/dev` (la contraseña va de `secretos` a RDS y el endpoint de RDS vuelve al secreto `db`) sin ciclo, porque Terraform resuelve las dependencias recurso por recurso. La **notificación** del bucket (`aws_s3_bucket_notification`) se crea después de la política de la cola, porque S3 valida el destino al guardarla. Entradas, salidas y recursos en §5.12 |
| **INF-1.3 Cómputo** | Módulo `computo` (30 recursos; entradas, salidas y nombres internos en §5.12): repositorios ECR (etiquetas inmutables, escaneo al subir, conservar 5), clúster sin *Container Insights*, espacio de nombres privado `campus-locator.local` con los servicios de Cloud Map `api` (A + SRV) y `embedding` (A), TTL 10 s, los cinco *log groups* de los procesos, el rol de ejecución y los cuatro roles de tarea de §5.8 (todos con el *boundary*, que `envs/dev` lee de los outputs de `bootstrap` con `terraform_remote_state`), las cinco definiciones de tarea (imagen inicial `:bootstrap`, la imagen de prueba de §5.11, que CI reemplaza; la de validación usa `postgres:17-alpine`) y los servicios `api`, `worker` y `embedding` con `desired_count = 0` hasta el primer despliegue. La imagen de prueba se publica a mano tras el `apply` (`pruebas/imagen-prueba/README.md`): los servicios en 0 no la necesitan para crearse. `validate13.py` sube `api` y `embedding` a 1 solo mientras valida |
| **INF-1.4 Borde** | Módulo `borde` (7 recursos; entradas, salidas y nombres internos en §5.12): HTTP API `campus-locator-dev-api` con `prevent_destroy` (R8), VPC Link en `publica-a` y `publica-b` con el grupo `-vpclink`, una integración `HTTP_PROXY` privada hacia el servicio de Cloud Map `api` (su ARN sale del nuevo output `cloud_map_api_arn` de `computo`), las rutas `ANY /{proxy+}` y `POST /v1/auth/login` hacia esa integración, etapa `$default` con despliegue automático y el *throttling* de §5.10 (general en `DefaultRouteSettings`, login en `RouteSettings`) y *access logs* en JSON en `/campus-locator/dev/apigw`, que crea el propio módulo. Expone `api_base_url` (el `ApiEndpoint`, sin barra final). `validate14.py` sube `api` a 1 solo mientras valida |
| **INF-2.1 Encendido de `embedding` y escalado** | `src/ops/embedding.py` (`encender`, `apagar`, `estado`, con el contrato de §5.10; su clase `Operador` la reutilizan los validadores). En `borde`, el filtro de métricas `campus-locator-dev-localize` sobre los *access logs* (métrica `LocalizePeticiones`). En `computo`, `escalado.tf` (11 recursos): los objetivos de Application Auto Scaling de `embedding` y `worker` (rango 0-0 al crearse; después Terraform ignora el rango, que cambian `embedding.py` y las acciones programadas), tres políticas por pasos de capacidad exacta (`embedding-apagar` → 0, `worker-cola` → 1, `worker-colas-vacias` → 0), las cuatro alarmas de expresión que las disparan (inactividad de 45 de 45 min; subida de `worker` con mensajes y CPU de `embedding` en el mismo minuto; bajada tras 15 de 15 min sin mensajes) y las dos acciones de las 22:00 (`America/Bogota`, rango 0-0). `envs/dev` define la métrica (`local.metrica_localize`) y se la pasa a los dos módulos, que así no se referencian entre sí, y la variable `apagado_embedding`. Decisiones en ADR-INF-15; nombres internos en §5.12 |
| **INF-3.1 Observabilidad** | Módulo `observabilidad` (11 recursos; entradas, salidas y nombres internos en §5.12): topic SNS `campus-locator-dev-alertas` sin cifrar, con política propia (la cuenta; CloudWatch; EventBridge solo desde la regla) y suscripción por correo a `correo_alertas` (hay que confirmarla desde el correo que envía SNS), las 6 alarmas de §5.10 con acción solo en `ALARM` hacia el topic, y la regla `campus-locator-dev-tarea-detenida` de §3.8 con el topic como destino (el evento va tal cual). Para no adivinar nombres, `borde`, `computo` y `datos` exponen `api_id`, `cluster_arn` y `rds_identificador`, que `envs/dev` le pasa junto con `servicios` y `colas`; `envs/dev` declara `correo_alertas` y expone `sns_alertas_arn`. Ningún recurso existente cambia (`plan`: 11 altas). `LectorCola` pasa de `validate21.py` a `comun.py` (§5.11), porque `validate31.py` también borra mensajes de prueba de una cola. `validate31.py` no toca los servicios: C2 deja un mensaje marcado en una DLQ vacía y lo borra; C3 lanza la tarea de validación con `startedBy = validacion-3-1` y un comando que sale con 3, y C1b prueba la rama de los servicios de la regla con `events:TestEventPattern`. 0.15.0 cambió el patrón de la regla (una rama `$or` para esa tarea: ECS no admite `group = service:…` en una tarea suelta) y la política del topic pasó a nombrar la regla por su ARN escrito, sin referencia al recurso (`plan`: 1 cambio en sitio). Decisiones en ADR-INF-16 |
| **INF-6.1 Producción** (diferido) | Ver PLAN, Fase 6 |

---

## 5. Interfaces (contratos)

> **Única fuente de verdad** de lo que esta carpeta expone. Cualquier otro documento que mencione estos nombres lo
> hace por referencia. Un cambio aquí sube la versión de este documento y exige entrada en `CHANGELOG.md`.

### 5.1 Convenciones de nombres y etiquetas

- Prefijo de recursos: `campus-locator-<entorno>-` (hoy `campus-locator-dev-`). Nombres globales (buckets) añaden el
  ID de la cuenta al final.
- Recursos que no dependen del entorno (repositorios ECR, roles de GitHub, bucket de estado, presupuesto) usan solo
  `campus-locator`.
- Etiquetas obligatorias (`default_tags`): `Proyecto = campus-locator`, `Entorno = dev`, `GestionadoPor = terraform`,
  `Carpeta = INFRASTRUCTURA_TERRAFORM`.
- Los recursos de red (VPC, subredes, Internet Gateway, tablas, endpoint y grupos) llevan además `Name` = su nombre
  del inventario; las reglas de los grupos solo llevan las cuatro de `default_tags`.

Inventario de nombres:

| Recurso | Nombre |
|---|---|
| VPC | `campus-locator-dev-vpc` (`10.20.0.0/16`) |
| Subredes | `campus-locator-dev-publica-a` `10.20.0.0/24` (us-east-1a) · `campus-locator-dev-publica-b` `10.20.1.0/24` (us-east-1b) · `campus-locator-dev-privada-a` `10.20.10.0/24` · `campus-locator-dev-privada-b` `10.20.11.0/24` |
| Internet Gateway | `campus-locator-dev-igw` |
| Tablas de rutas | `campus-locator-dev-publica` (las dos públicas) · `campus-locator-dev-privada` (las dos privadas) |
| Endpoint de S3 (*gateway*) | `campus-locator-dev-s3` |
| Grupos de seguridad | `campus-locator-dev-vpclink`, `-api`, `-worker`, `-embedding`, `-rds`; el `default` de la VPC lleva `Name = campus-locator-dev-default` |
| HTTP API / VPC Link | `campus-locator-dev-api` / `campus-locator-dev-vpclink` |
| Clúster ECS | `campus-locator-dev` |
| Servicios ECS | `api`, `worker`, `embedding` |
| Familias de definición de tarea | `campus-locator-dev-api`, `campus-locator-dev-worker`, `campus-locator-dev-embedding`, `campus-locator-dev-migrate`, `campus-locator-dev-validacion` (§5.11) |
| Contenedor dentro de cada tarea | `app` (todas las tareas tienen un solo contenedor con ese nombre) |
| Espacio de nombres Cloud Map | `campus-locator.local` (DNS privado de la VPC) |
| Repositorios ECR | `campus-locator/backend`, `campus-locator/embedding` |
| RDS | instancia `campus-locator-dev-db`, base `campus_locator`, usuario `campus_app`, grupo de parámetros `campus-locator-dev-pg17`, grupo de subredes `campus-locator-dev-db`, *snapshot* final `campus-locator-dev-db-final` |
| Bucket del dataset | `campus-locator-dev-dataset-648617469176` |
| Bucket de estado | `campus-locator-tfstate-648617469176` (claves: `bootstrap/terraform.tfstate`, `dev/terraform.tfstate`) |
| Colas SQS | `campus-locator-dev-ingesta`, `campus-locator-dev-ingesta-dlq`, `campus-locator-dev-purga`, `campus-locator-dev-purga-dlq` |
| Topic SNS | `campus-locator-dev-alertas` (una suscripción `email` a `correo_alertas`, INF-3.1) |
| Secretos | `campus-locator/dev/db`, `campus-locator/dev/jwt`, `campus-locator/dev/admin-inicial` |
| Log groups | `/campus-locator/dev/api`, `/campus-locator/dev/worker`, `/campus-locator/dev/embedding`, `/campus-locator/dev/migrate`, `/campus-locator/dev/validacion`, `/campus-locator/dev/apigw` |
| Streams de log de las tareas | `awslogs-stream-prefix` = nombre del proceso (`api`, `worker`, `embedding`, `migrate`, `validacion`); cada tarea escribe en `<proceso>/app/<id-de-la-tarea>` (p. ej. `embedding/app/0f3c9a…`). Una tarea suelta lanzada con la definición de `embedding` escribe en `/campus-locator/dev/embedding` con el mismo formato |
| Roles IAM | `campus-locator-dev-ecs-ejecucion`, `campus-locator-dev-tarea-api`, `campus-locator-dev-tarea-worker`, `campus-locator-dev-tarea-embedding`, `campus-locator-dev-tarea-migrate`, `campus-locator-gha-terraform-plan`, `campus-locator-gha-terraform`, `campus-locator-gha-deploy` |
| *Permissions boundary* | `campus-locator-limite-roles` (política gestionada; obligatoria en los roles `campus-locator-*` que crea `envs/dev`, §5.8) |
| Presupuesto | `campus-locator-mensual` |
| Alarmas de CloudWatch (INF-3.1) | `campus-locator-dev-api-5xx`, `campus-locator-dev-ingesta-dlq`, `campus-locator-dev-purga-dlq`, `campus-locator-dev-embedding-encendida`, `campus-locator-dev-rds-almacenamiento`, `campus-locator-dev-rds-creditos-cpu` |
| Alarmas de escalado (INF-2.1) | `campus-locator-dev-worker-cola-ingesta`, `campus-locator-dev-worker-cola-purga` (subir `worker`), `campus-locator-dev-worker-colas-vacias` (bajarlo), `campus-locator-dev-embedding-inactivo` (apagar `embedding`) |
| Políticas de escalado (INF-2.1) | `campus-locator-dev-worker-cola` (sube `worker` a 1), `campus-locator-dev-worker-colas-vacias` (lo baja a 0), `campus-locator-dev-embedding-apagar` (`embedding` a 0); las tres por pasos con capacidad exacta |
| Acciones programadas | `campus-locator-dev-embedding-apagar-noche`, `campus-locator-dev-worker-apagar-noche` (INF-2.1) |
| Filtro de métricas (INF-2.1) | `campus-locator-dev-localize` sobre `/campus-locator/dev/apigw` → métrica `LocalizePeticiones` del espacio `campus-locator/dev` |
| Métricas propias (INF-2.1) | espacio `campus-locator/dev`, sin dimensiones: `LocalizePeticiones` (la publica el filtro) y `EmbeddingEncendidos` (la publica `embedding.py encender`, §5.10) |
| Regla de EventBridge | `campus-locator-dev-tarea-detenida` (bus `default`; destino con id `sns-alertas` → el topic, INF-3.1) |
| Entorno de GitHub | `dev` (§3.9) |
| Workflows | `infra.yml`, `backend.yml`, `embedding.yml`, `frontend.yml` (§5.9) |

### 5.2 Outputs de Terraform (`envs/dev`)

| Output | Ejemplo / forma | Quién lo usa |
|---|---|---|
| `api_base_url` | `https://fuzq99kddb.execute-api.us-east-1.amazonaws.com` (valor real en `dev`, sin barra final; cambia si se recrea la API, R8) | App: `ApiConfig.kt` = este valor + `/v1`. Lo que ve el cliente en esa URL sin pasar por `api`: §5.13 |
| `ecr_backend_url` | `648617469176.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend` | `backend.yml` |
| `ecr_embedding_url` | `…/campus-locator/embedding` | `embedding.yml` |
| `ecs_cluster` | `campus-locator-dev` | workflows |
| `ecs_servicios` | `{ api = "api", worker = "worker", embedding = "embedding" }` | workflows |
| `familias_tarea` | `{ api, worker, embedding, migrate, validacion }` → nombres de §5.1 | workflows y validadores |
| `subredes_tareas` | lista con el ID de `publica-a` | `run-task` de `migrate` |
| `sg_migrate` | ID del grupo de seguridad que usa `migrate` (el de `api`) | `run-task` de `migrate` y de la tarea de validación |
| `bucket_dataset` | `campus-locator-dev-dataset-648617469176` | depuración |
| `sqs_ingesta_url`, `sqs_purga_url`, `sqs_ingesta_dlq_url`, `sqs_purga_dlq_url` | URLs de SQS | depuración y re-procesado manual |
| `rds_endpoint` | `campus-locator-dev-db.xxxx.us-east-1.rds.amazonaws.com` | depuración |
| `secretos` | `{ db, jwt, admin_inicial }` → ARN | depuración |
| `embedding_dns` | `embedding.campus-locator.local` | depuración |
| `sns_alertas_arn` | `arn:aws:sns:us-east-1:648617469176:campus-locator-dev-alertas` | `validate31.py`; depuración (suscripciones, `aws sns publish` de prueba) |
| `bootstrap: rol_gha_terraform_plan_arn`, `rol_gha_terraform_arn`, `rol_gha_deploy_arn`, `bucket_estado`, `github_repo` | ARN / nombre | variables del repositorio de GitHub (§5.9) y validadores de INF-0.x |
| `bootstrap: limite_roles_arn` | ARN de `campus-locator-limite-roles` | `envs/dev`: `permissions_boundary` de todos sus roles (INF-1.3; lo lee con `data "terraform_remote_state" "bootstrap"`, §5.12) |

Ningún servicio lee outputs en tiempo de ejecución: todo lo que necesitan llega por variables de entorno (§5.4).
Los outputs aparecen con el lote que crea su recurso: `api_base_url` con INF-1.4, `sns_alertas_arn` con INF-3.1,
`subredes_tareas` y `sg_migrate` con INF-1.1, `bucket_dataset`, las cuatro `sqs_*_url`, `rds_endpoint` y `secretos`
con INF-1.2 y el resto con INF-1.3. Desde INF-0.2, `envs/dev` tiene además el output `cuenta_id` (de un
`data "aws_caller_identity"`, que obliga a evaluar el proveedor y su `allowed_account_ids` aunque no haya recursos).

### 5.3 Variables de entrada

`bootstrap/terraform.tfvars` y `envs/dev/terraform.tfvars` (columna «Dónde»). Los dos archivos se versionan: no
contienen secretos. Cada variable de `envs/dev` se declara con el lote que la usa (INF-0.2: `aws_account_id`, `region`,
`proyecto` y `entorno`; INF-1.1: `cidr_vpc`, `az_computo` y `az_secundaria`; INF-1.2: `rds_clase`, `rds_gb`,
`rds_gb_max` y `pg_version`; INF-1.3: `imagen_inicial_tag`; INF-2.1: `apagado_embedding`; INF-3.1: `correo_alertas`).

| Variable | Dónde | Valor en `dev` | Notas |
|---|---|---|---|
| `aws_account_id` | ambos | `"648617469176"` | Va a `allowed_account_ids` |
| `region` | ambos | `"us-east-1"` | |
| `proyecto` / `entorno` | ambos | `"campus-locator"` / `"dev"` | Forman el prefijo de §5.1 |
| `cidr_vpc` | `envs/dev` | `"10.20.0.0/16"` | Debe ser una /16 (lo valida el módulo `red`): las subredes son sus /24 número 0, 1, 10 y 11 (§5.1) |
| `az_computo` | `envs/dev` | `"us-east-1a"` | Zona única de tareas y RDS; aloja `publica-a` y `privada-a` |
| `az_secundaria` | `envs/dev` | `"us-east-1b"` | Solo para `publica-b` y `privada-b`: el grupo de subredes de RDS exige dos zonas (ADR-INF-03) |
| `github_repo` | `bootstrap` | `"Ang3l1485/Proyecto_4U"` | Con las mayúsculas exactas de GitHub. Lo usan los *trust policies* de OIDC; `bootstrap` lo expone como output `github_repo` |
| `github_ids` | `bootstrap` | `{ propietario = 142058005, repositorio = 1362957467 }` | IDs inmutables del `sub` de OIDC (§5.8): el repositorio se creó después del 2026-07-15. `null` = formato clásico |
| `correo_alertas` | ambos | *(el de `bootstrap/terraform.tfvars`; el mismo valor en los dos archivos)* | Presupuesto (`bootstrap`) y suscripción del topic de alarmas (`envs/dev`, INF-3.1). Los dos lo validan como dirección de correo. En `envs/dev`, cambiarlo reemplaza la suscripción (la nueva hay que confirmarla); `validate31.py` C1c lo lee de `envs/dev/terraform.tfvars` |
| `presupuesto_usd` | `bootstrap` | `100` | |
| `apagado_embedding` | `envs/dev` | `{ zona = "America/Bogota", noche = "cron(0 22 * * ? *)", inactividad_min = 45 }` | Apagado automático de `embedding` (INF-2.1): `zona` IANA y `noche` en el formato `cron(...)` de Application Auto Scaling para las dos acciones nocturnas (`noche = null` u omitida las quita; `validate21.py` exige que existan); `inactividad_min`, entero entre 5 y 1440 (periodos de 60 s de la alarma; lo valida el módulo `computo`) |
| `imagen_inicial_tag` | `envs/dev` | `"bootstrap"` | Imagen de las definiciones de tarea que crea Terraform. CI registra revisiones con su imagen (ADR-INF-09); cambiarla solo crea revisiones nuevas, que ningún servicio usa hasta el siguiente despliegue |
| `rds_clase` / `rds_gb` / `rds_gb_max` | `envs/dev` | `"db.t4g.micro"` / `20` / `50` | `rds_gb_max` debe ser mayor que `rds_gb` (lo valida el módulo `datos`) |
| `pg_version` | `envs/dev` | `"17"` | Solo la versión mayor (lo valida el módulo `datos`): RDS elige la menor por defecto (≥ 17.1, pgvector 0.8.x) y la actualiza. Forma también la familia (`postgres17`) y el nombre del grupo de parámetros |

### 5.4 Variables de entorno y secretos por proceso

Valores que **inyecta la infraestructura**. Qué hace cada servicio con ellos lo define su propio §5.

**Secretos** (JSON en Secrets Manager; ECS inyecta cada clave como variable):

| Secreto | Claves | Variable inyectada ← clave | Procesos |
|---|---|---|---|
| `campus-locator/dev/db` | `host`, `port`, `dbname`, `username`, `password` | `DB_PASSWORD` ← `password` (en la tarea de validación, `PGPASSWORD`) | `api`, `worker`, `migrate`, `validacion` |
| `campus-locator/dev/jwt` | `secret` (64 bytes aleatorios codificados en base64; el backend usa la cadena tal cual como clave HMAC, sin decodificarla) | `JWT_SECRET` ← `secret` | `api` |
| `campus-locator/dev/admin-inicial` | `correo`, `password` | `ADMIN_INICIAL_CORREO` ← `correo`, `ADMIN_INICIAL_PASSWORD` ← `password` | `migrate` |

Formato de los valores (los genera el módulo `secretos`): `port` es un número JSON (`5432`) y el resto son cadenas; el
`password` de `db` tiene 40 caracteres alfanuméricos (no hay que escaparlo en una URL de conexión) y el de
`admin-inicial`, 24 alfanuméricos con al menos 2 mayúsculas, 2 minúsculas y 2 dígitos. En una definición de tarea, cada
variable se inyecta con `valueFrom = "<ARN del secreto>:<clave>::"` (output `secretos`).

El secreto `admin-inicial` lo crea Terraform con `correo = "admin@campus.edu.co"` (el mismo de las pruebas de la
app) y contraseña aleatoria; se consulta en la consola para el primer inicio de sesión y se cambia después.

**Variables en texto plano:**

| Variable | `api` | `worker` | `migrate` | `embedding` | Valor en `dev` |
|---|---|---|---|---|---|
| `APP_ENV` | ✓ | ✓ | ✓ | ✓ | `dev` |
| `AWS_REGION` | ✓ | ✓ | ✓ | | `us-east-1` |
| `LOG_LEVEL` | ✓ | ✓ | ✓ | ✓ | `INFO` |
| `DB_HOST` | ✓ | ✓ | ✓ | | endpoint de RDS (sin puerto) |
| `DB_PORT` | ✓ | ✓ | ✓ | | `5432` |
| `DB_NAME` | ✓ | ✓ | ✓ | | `campus_locator` |
| `DB_USER` | ✓ | ✓ | ✓ | | `campus_app` |
| `DB_SSLMODE` | ✓ | ✓ | ✓ | | `require` |
| `S3_BUCKET_DATASET` | ✓ | ✓ | | | `campus-locator-dev-dataset-648617469176` |
| `SQS_URL_INGESTA` | ✓ | ✓ | | | URL de `campus-locator-dev-ingesta` |
| `SQS_URL_PURGA` | ✓ | ✓ | | | URL de `campus-locator-dev-purga` |
| `EMBEDDING_URL` | ✓ | ✓ | | | `http://embedding.campus-locator.local:8080` |
| `TORCH_NUM_THREADS` | | | | ✓ | `2` (= vCPU de la tarea) |

Parámetros de comportamiento (tiempo de vida del JWT, umbrales de localización, tamaños de lote, etc.) **no** los
inyecta Terraform: tienen valor por defecto en el código y están en el §5 de cada servicio. Si un parámetro se
quiere mover a variable de entorno, se añade primero a esta tabla.

### 5.5 Bucket del dataset

`campus-locator-dev-dataset-648617469176`

| Prefijo | Contenido | Quién escribe | Quién lee | Formato de la clave |
|---|---|---|---|---|
| `dataset/` | Fotos originales del dataset | La app, con URL prefirmada de `api` | `worker` | `dataset/{video_id}/{imagen_id}.jpg` |
| `thumbs/` | Miniaturas (tamaño: backend §5.10) | `worker` | La app, con URL prefirmada de `api` | `thumbs/{video_id}/{imagen_id}.jpg` |
| `lugares/` | Foto opcional de cada lugar (reservado, Fase 4) | `api` | La app, con URL prefirmada | `lugares/{lugar_id}.jpg` |
| `evaluacion/` | Conjunto de fotos de consulta de EMB-3.2 (y su `puntos.json` con coordenadas reales) | Personas del equipo, con sus credenciales | Validadores de EMB-3.2 y BE-3.2 | `evaluacion/<version_conjunto>/…` |

- `video_id` e `imagen_id` son UUID en minúsculas (los genera el backend; ver su §5).
- **Notificación**: `s3:ObjectCreated:*` con filtro `prefix = "dataset/"`, `suffix = ".jpg"` → cola
  `campus-locator-dev-ingesta`. Ningún otro prefijo genera eventos.
- Cifrado SSE-S3, *Block Public Access* completo, sin CORS (la app es nativa).
- Política del bucket: una sola declaración, que deniega `s3:*` a cualquiera si la petición no usa TLS
  (`aws:SecureTransport = false`). Los permisos los dan las políticas de identidad (§5.8); las URL prefirmadas que firma
  `api` deben ser `https://` (las de boto3 lo son por defecto).
- Ciclo de vida: abortar subidas multiparte incompletas a los 7 días. Los objetos no expiran (el borrado lo hace la
  purga).
- Las fotos de `/v1/localize` no se escriben en ningún bucket.

### 5.6 Colas y topics

| Cola | Visibilidad | Retención | Espera larga | Reintentos → DLQ | Productor | Consumidor |
|---|---|---|---|---|---|---|
| `campus-locator-dev-ingesta` | 180 s | 4 días | 20 s | 5 → `campus-locator-dev-ingesta-dlq` | S3 (notificación) y `api` (re-procesar) | `worker` |
| `campus-locator-dev-purga` | 300 s | 4 días | 20 s | 5 → `campus-locator-dev-purga-dlq` | `api` | `worker` |
| DLQ (ambas) | — | 14 días | — | — | SQS | persona (re-envío manual con *redrive*) |

- Todas cifradas con SSE-SQS. La política de recurso de `ingesta` concede `sqs:SendMessage` al servicio
  `s3.amazonaws.com` solo con `aws:SourceArn` = el bucket del dataset y `aws:SourceAccount` = la cuenta; el rol de
  tarea de `api` envía con su política de identidad (§5.8). `purga` y las DLQ no tienen política de recurso.
- El **formato de los mensajes** (incluido cómo tratar el `s3:TestEvent` que S3 envía al configurar la notificación)
  lo define `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.8. Tras el `apply` de INF-1.2 queda uno en `ingesta`;
  `validate12.py` lo borra (`validation-1-2` §4).
- **Topic SNS** `campus-locator-dev-alertas` (INF-3.1): lo publican las 6 alarmas de §5.10 y la regla de EventBridge
  `campus-locator-dev-tarea-detenida` (§3.8); AWS Budgets no (escribe directamente al correo, §3.8). Una suscripción
  `email` a `correo_alertas`, que hay que confirmar. Sin cifrado (ADR-INF-16). No lo usa ningún servicio.
  Su política (declaraciones por `Sid`):

  | `Sid` | Principal | Acciones | Condición |
  |---|---|---|---|
  | `Cuenta` | `AWS: *` | las ocho de la política por defecto de SNS (`SNS:AddPermission`, `DeleteTopic`, `GetTopicAttributes`, `ListSubscriptionsByTopic`, `Publish`, `RemovePermission`, `SetTopicAttributes`, `Subscribe`) | `StringEquals AWS:SourceOwner = 648617469176` (la de por defecto: reemplazar la política la quitaría) |
  | `CloudWatch` | servicio `cloudwatch.amazonaws.com` | `sns:Publish` | `aws:SourceAccount = 648617469176` y `aws:SourceArn` como `arn:aws:cloudwatch:us-east-1:648617469176:alarm:*` |
  | `EventBridge` | servicio `events.amazonaws.com` | `sns:Publish` | `ArnEquals aws:SourceArn` = la regla `campus-locator-dev-tarea-detenida` |

  Para probar la entrega a mano: `aws sns publish --topic-arn <sns_alertas_arn> --subject prueba --message prueba`
  (con la suscripción confirmada debería llegar un correo «prueba»; sin comprobar).

### 5.7 Red: puertos, grupos de seguridad, DNS interno y salud

| Grupo | Entrante | Saliente |
|---|---|---|
| `campus-locator-dev-vpclink` | — | `8000/tcp` hacia `-api` |
| `campus-locator-dev-api` | `8000/tcp` desde `-vpclink` | todo (internet por IGW) |
| `campus-locator-dev-worker` | — | todo |
| `campus-locator-dev-embedding` | `8080/tcp` desde `-api` y `-worker` | todo (solo lo usa para logs y ECR) |
| `campus-locator-dev-rds` | `5432/tcp` desde `-api` y `-worker` | — |

`migrate` y la tarea de validación (§5.11) usan el grupo `-api`.

- «todo» = todos los protocolos y puertos hacia `0.0.0.0/0` (la VPC no tiene IPv6).
- El grupo `default` de la VPC no tiene reglas (§3.2) y ningún recurso lo usa: todo recurso con interfaz en la VPC
  declara uno de estos cinco grupos.
- Todas las reglas de estos grupos viven en el módulo `red` (§5.12): otro módulo no crea grupos ni les añade reglas.
  Cambiar una regla es editar este cuadro, `modules/red/main.tf` y `REGLAS_ESPERADAS` de `validate11.py` en el mismo
  cambio.
- La descripción de un grupo es fija (cambiarla obliga a recrearlo, y con él todo lo que lo usa) y AWS solo admite
  ASCII en ella y en la de las reglas: sin tildes ni `§`.

| Nombre DNS (Cloud Map, privado) | Registro | Puerto | Para qué |
|---|---|---|---|
| `api.campus-locator.local` | SRV (+A) | 8000 | Integración de API Gateway |
| `embedding.campus-locator.local` | A, TTL 10 s | 8080 | `api` y `worker` llaman a embeddings |

**Health checks de contenedor** (los endpoints los define cada servicio en su §5):

| Proceso | Comando | Intervalo / reintentos / *start period* |
|---|---|---|
| `api` | `python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3)"` | 30 s / 3 / 30 s |
| `embedding` | igual contra `http://127.0.0.1:8080/health/ready` | 30 s / 3 / **180 s** (carga del modelo) |
| `worker` | sin health check HTTP; ECS solo vigila que el proceso siga vivo | — |

### 5.8 Permisos IAM

| Rol | Permisos | Recursos |
|---|---|---|
| `campus-locator-dev-ecs-ejecucion` | `AmazonECSTaskExecutionRolePolicy` + `secretsmanager:GetSecretValue` | los tres secretos |
| `campus-locator-dev-tarea-api` | `s3:PutObject`, `s3:GetObject` (para firmar URLs) | objetos `dataset/*`, `thumbs/*`, `lugares/*` del bucket |
| | `sqs:SendMessage` | colas `purga` e `ingesta` (re-procesar una imagen) |
| | `ssmmessages:*Channel` (ECS Exec, depuración) | `*` |
| `campus-locator-dev-tarea-worker` | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` | objetos `dataset/*`, `thumbs/*`, `lugares/*` |
| | `s3:ListBucket` (para la purga) | el ARN del **bucket**, con condición `s3:prefix` ∈ {`dataset/*`, `thumbs/*`} |
| | `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes` | colas `ingesta` y `purga` |
| `campus-locator-dev-tarea-migrate` | ninguno sobre AWS (la base usa usuario y contraseña); también lo usa la tarea de validación | — |
| `campus-locator-dev-tarea-embedding` | ninguno sobre AWS | — |
| `campus-locator-gha-deploy` | `ecr:GetAuthorizationToken`; `ecr:*Layer*`, `ecr:PutImage`, `ecr:BatchGetImage` sobre los dos repositorios; `ecs:RegisterTaskDefinition`, `ecs:DescribeTaskDefinition`, `ecs:UpdateService`, `ecs:DescribeServices`, `ecs:RunTask`, `ecs:DescribeTasks` sobre el clúster; `iam:PassRole` sobre los roles de ejecución y de tarea; `logs:GetLogEvents` sobre `/campus-locator/dev/migrate` | |
| `campus-locator-gha-terraform-plan` | `ReadOnlyAccess`; lectura del bucket de estado y escritura solo del archivo de bloqueo `dev/terraform.tfstate.tflock` | |
| | `secretsmanager:GetSecretValue` (el `plan` refresca `aws_secretsmanager_secret_version`; esos valores ya están en el estado, R5) | secretos `campus-locator/dev/*` |
| `campus-locator-gha-terraform` | `PowerUserAccess` + IAM limitado a roles y políticas con prefijo `campus-locator-`; crear un rol o cambiar sus políticas exige el boundary `campus-locator-limite-roles`; lectura y escritura del bucket de estado | |
| | Denegado: salir de la región (salvo servicios globales), tocar los roles `campus-locator-gha-*`, quitar o editar el boundary, `sts:AssumeRole`, cambiar la configuración del bucket de estado, borrar versiones del estado y escribir `bootstrap/*` | |
| `campus-locator-limite-roles` (*permissions boundary*) | Techo de todo rol que crea `envs/dev`: todo menos `iam:*`, `organizations:*`, `account:*` y `sts:AssumeRole`, con las mismas denegaciones de región y del bucket de estado que `gha-terraform`. Los roles `ecs-ejecucion` y `tarea-*` de esta tabla lo llevan como `permissions_boundary` (ADR-INF-12) | |

*Trust policy* de los roles de GitHub (proveedor `token.actions.githubusercontent.com`, `aud = sts.amazonaws.com`).
`<sub_repo>` es el segmento del repositorio en el *claim* `sub`: GitHub usa el formato inmutable
`propietario@ID/repo@ID` en los repositorios creados, renombrados o transferidos después del 2026-07-15 (este:
`Ang3l1485@141779168/Proyecto_4U@1312078315`, variable `github_ids`) y `propietario/repo` en los demás.
- `gha-deploy`: `sub` = `repo:<sub_repo>:ref:refs/heads/main`.
- `gha-terraform-plan`: `sub` = `repo:<sub_repo>:pull_request`. El código de un PR solo puede leer: no puede aplicar
  cambios aunque modifique el workflow.
- `gha-terraform`: `sub` = `repo:<sub_repo>:environment:dev` (el entorno de GitHub exige aprobación manual y solo
  admite la rama `main`, §3.9).

### 5.9 Contrato de despliegue (CI/CD)

**Imágenes**
- Plataforma `linux/amd64`. Etiqueta = SHA completo del commit (`${GITHUB_SHA}`); etiquetas inmutables, sin `latest`.
- Cada servicio aporta su `Dockerfile` en `<CARPETA>/project/Dockerfile`; el contexto de construcción es
  `<CARPETA>/project/`. `src/ops/` y `tests/` quedan fuera de la imagen (`.dockerignore`), salvo lo que cada servicio
  declare en su §5. El proceso por defecto de la imagen del backend es
  el servidor HTTP; `worker` y `migrate` sobrescriben el comando en su definición de tarea (los comandos los fija
  `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.9).

**Secuencia de `backend.yml` (en `main`)**
1. Pruebas → `docker build` → `push` a `ecr_backend_url:<sha>`.
2. Nueva revisión de `campus-locator-dev-migrate` con la imagen nueva → `ecs run-task` (Fargate, subred
   `subredes_tareas`, grupo `sg_migrate`, IP pública) → esperar `STOPPED` → **falla el workflow si el código de salida
   del contenedor `app` no es 0** (se imprime el log de `/campus-locator/dev/migrate`).
3. Nuevas revisiones de `campus-locator-dev-api` y `campus-locator-dev-worker` → `update-service` de ambos →
   `wait services-stable` sobre `api`.

**Secuencia de `embedding.yml` (en `main`)**: pruebas → imagen → nueva revisión de `campus-locator-dev-embedding` →
`update-service` → `wait services-stable` (solo si `embedding` está encendido; apagado, queda en 0 y toma la revisión
nueva al encenderse).

**Primer despliegue**: el primer `backend.yml` además pone `desired_count = 1` en `api`; `embedding` se enciende a mano
(§3.4) y `worker` escala solo.

**`infra.yml`** (INF-0.2; la secuencia completa está en §3.9). Lo que otros archivos dan por fijo:

| Elemento | Valor | Quién depende de él |
|---|---|---|
| Disparadores | `pull_request` y `push` a `main` con cambios en `INFRASTRUCTURA_TERRAFORM/project/**` o en `.github/workflows/infra.yml` | — |
| Job de PR | `plan (PR)`: rol `vars.AWS_ROL_TERRAFORM_PLAN_ARN`; pasos `terraform fmt -check`, `tflint`, `terraform validate`, `terraform plan`, `Comentar el plan en el PR` | `validate02.py` C1 (busca el job por el prefijo `plan` y esos cuatro primeros pasos por nombre) |
| Comentario del plan | uno por PR, de `github-actions[bot]`, con la marca `<!-- infra-plan envs/dev -->`; se actualiza en cada ejecución | `validate02.py` C1 |
| Job de `main` | `apply (main)`: entorno `dev`, rol `vars.AWS_ROL_TERRAFORM_ARN`; `plan -out=tfplan` y `apply tfplan` | `validate02.py` C2 (prefijo `apply`; busca `Apply complete!` en su log) |
| Versiones | `env.TF_VERSION` (= la del equipo, hoy `1.16.6`) y `env.TFLINT_VERSION` (`v0.65.0`); acciones fijadas por SHA con la versión en un comentario | Cambiar `TF_VERSION` exige que el equipo use la misma en local (P5 de `validation-0-2` avisa si difiere) |
| Variables que lee | `AWS_REGION`, `AWS_ROL_TERRAFORM_PLAN_ARN`, `AWS_ROL_TERRAFORM_ARN` | — |

Renombrar un job, uno de esos pasos o la marca del comentario rompe `validate02.py`: se cambian los dos en el mismo
commit.

**Variables del repositorio de GitHub** (*Settings → Variables*, no secretos):
`AWS_REGION`, `AWS_ROL_DEPLOY_ARN`, `AWS_ROL_TERRAFORM_PLAN_ARN`, `AWS_ROL_TERRAFORM_ARN`, `ECR_BACKEND`,
`ECR_EMBEDDING`, `ECS_CLUSTER`,
`SUBREDES_TAREAS`, `SG_MIGRATE`. Se copian de los outputs de §5.2 tras cada `apply` que los cambie. No se guardan
llaves de AWS en GitHub. Formato: `SUBREDES_TAREAS` = IDs de subred separados por comas, sin espacios (hoy solo
`publica-a`); `SG_MIGRATE` = un ID de grupo. Los dos existen desde INF-1.1; `ECR_*` y `ECS_CLUSTER`, desde INF-1.3.

### 5.10 Parámetros operativos

| Parámetro | Valor en `dev` |
|---|---|
| Tamaños de tarea | §3.4 |
| Encendido de `embedding` | Apagado por defecto; a mano con `embedding.py encender` (contrato abajo); se apaga tras `inactividad_min` (45) min seguidos sin peticiones a `POST /v1/localize`, sin muestras de `EmbeddingEncendidos` y sin mensajes visibles ni en vuelo en `ingesta` y `purga` (alarma `embedding-inactivo`: 45 de 45 periodos de 60 s con la suma < 0,5), y a las 22:00 `America/Bogota` (rango 0-0) |
| Contrato de encendido (`embedding.py encender`; lo siguen también los validadores que necesitan `embedding`, §5.11) | 1) `RegisterScalableTarget` de `embedding` y `worker` con mínimo 0 y máximo 1 (si el objetivo no existe, INF-2.1 no está aplicado: no se crea); 2) `PutMetricData` de `EmbeddingEncendidos` = 1 (`Count`) en `campus-locator/dev`; 3) esperar a que `GetMetricStatistics` devuelva esa muestra, un minuto más y que la alarma `campus-locator-dev-embedding-inactivo` no esté en `ALARM` (hasta 5 min); 4) `UpdateService` de `embedding` a 1; 5) esperar tarea `HEALTHY`, despliegue `COMPLETED` e instancia sana en Cloud Map (hasta 10 min desde el paso 1). **Apagado** (`embedding.py apagar`): `RegisterScalableTarget` 0-0 y `UpdateService` a 0 de `embedding` y `worker` |
| Latencia objetivo de `POST /v1/localize` | p95 de `integrationLatency` (*access logs*) ≤ 1000 ms con `embedding` encendido |
| Escalado de `worker` | sube a 1 con ≥ 1 mensaje visible en `ingesta` o `purga` y una muestra de `CPUUtilization` de `embedding` en el mismo minuto (1 de 10 periodos de 60 s; una alarma por cola); baja a 0 tras 15 periodos seguidos sin mensajes visibles ni en vuelo en las dos, y también con `embedding.py apagar` o a las 22:00 (rango 0-0) |
| Throttling API Gateway | general: 20 req/s, ráfaga 40 · `POST /v1/auth/login`: 2 req/s, ráfaga 5 (valores configurados; AWS los aplica de forma aproximada, §3.3) |
| Formato de los *access logs* | JSON por línea: `requestId`, `ip`, `requestTime`, `httpMethod`, `routeKey`, `path`, `status`, `responseLength`, `integrationLatency`, `integrationStatus` (`requestId` es el encabezado `apigw-requestid` de la respuesta). Todos los valores son **cadenas** (`"status":"200"`; API Gateway escribe `"-"` si un dato no existe, p. ej. `integrationLatency` en un 429), así toda línea es JSON válido; quien calcule con `integrationLatency` la convierte a número |
| Retención de logs | 14 días (todos los log groups) |
| Copias de RDS | 7 días; ventana 07:00–07:30 UTC (02:00 en Bogotá, de madrugada) |
| Mantenimiento de RDS | domingos 08:00–09:00 UTC (03:00 en Bogotá); versión menor automática |
| `rds.force_ssl` / `max_connections` | `1` / por defecto de la clase |
| Alarmas | `5xx` de la API > 5 en 5 min · cualquier DLQ con ≥ 1 mensaje · tarea detenida por error (EventBridge, §3.8) · `embedding` encendido más de 10 h seguidas · RDS `FreeStorageSpace` < 4 GiB (4 294 967 296 bytes) · RDS `CPUCreditBalance` < 20 (parámetros exactos abajo) |
| Presupuesto | 100 USD/mes; avisos 50 % y 80 % real, 100 % pronosticado |
| ECR | conservar las 5 imágenes más recientes por repositorio |

**Alarmas de INF-3.1, tal como quedan en AWS** (módulo `observabilidad`, §5.12). Todas: una sola métrica (sin
expresión), `DatapointsToAlarm = EvaluationPeriods`, `TreatMissingData = notBreaching`, `AlarmActions` = solo
`sns_alertas_arn`, sin `OKActions` ni `InsufficientDataActions`. Cambiar una es editar esta tabla,
`modules/observabilidad/main.tf` (`local.alarmas`, forma en §5.12), `alarmas_esperadas` de `validate31.py` y
`alarmas_bien()` de `tests/ops/falsos.py` en el mismo cambio (si `falsos.py` se queda atrás, fallan las pruebas).

| Alarma | Métrica (espacio · nombre · dimensiones) | Estadística · periodo · periodos | Condición |
|---|---|---|---|
| `campus-locator-dev-api-5xx` | `AWS/ApiGateway` · `5xx` · `ApiId` = la de `campus-locator-dev-api` (`fuzq99kddb`) | `Sum` · 300 s · 1 | `GreaterThanThreshold` 5 |
| `campus-locator-dev-ingesta-dlq` | `AWS/SQS` · `ApproximateNumberOfMessagesVisible` · `QueueName = campus-locator-dev-ingesta-dlq` | `Maximum` · 60 s · 1 | `GreaterThanOrEqualToThreshold` 1 |
| `campus-locator-dev-purga-dlq` | igual con `QueueName = campus-locator-dev-purga-dlq` | `Maximum` · 60 s · 1 | `GreaterThanOrEqualToThreshold` 1 |
| `campus-locator-dev-embedding-encendida` | `AWS/ECS` · `CPUUtilization` · `ClusterName = campus-locator-dev`, `ServiceName = embedding` | `SampleCount` · 3600 s · 10 | `GreaterThanThreshold` 0 (hubo muestras en cada una de las 10 últimas horas; 10 × 3600 s cabe en el día que admite una alarma) |
| `campus-locator-dev-rds-almacenamiento` | `AWS/RDS` · `FreeStorageSpace` · `DBInstanceIdentifier = campus-locator-dev-db` | `Minimum` · 300 s · 1 | `LessThanThreshold` 4294967296 |
| `campus-locator-dev-rds-creditos-cpu` | `AWS/RDS` · `CPUCreditBalance` · `DBInstanceIdentifier = campus-locator-dev-db` | `Minimum` · 300 s · 1 | `LessThanThreshold` 20 |

Valores medidos el 2026-10-26 antes del `apply` (para saber que ninguna avisará al crearse): DLQ con 0 mensajes; RDS con
288 créditos (el máximo de `db.t4g.micro`) y ~18,4 GB libres; 1 respuesta 5xx en las últimas 24 h.

**Regla `campus-locator-dev-tarea-detenida`** (bus `default`, `ENABLED`). Patrón exacto desde 0.15.0 (las listas son
«cualquiera de»; `$or`, «alguna de las ramas»):
```json
{
  "source": ["aws.ecs"],
  "detail-type": ["ECS Task State Change"],
  "detail": {
    "clusterArn": ["arn:aws:ecs:us-east-1:648617469176:cluster/campus-locator-dev"],
    "lastStatus": ["STOPPED"],
    "stopCode": ["EssentialContainerExited", "TaskFailedToStart"],
    "$or": [
      { "group": ["service:api", "service:embedding", "service:worker"] },
      { "startedBy": ["validacion-3-1"] }
    ]
  }
}
```
La segunda rama es solo para la tarea de prueba de `validate31.py` C3 (`local.marca_prueba` del módulo): una tarea
suelta no puede llevar `group = service:…` (§3.8). Hasta 0.14.x, `detail` llevaba `group` directamente, sin `$or`.
Qué avisa y qué no lo comprueba `validate31.py` C1b con `events:TestEventPattern` (`CASOS_PATRON`, §5.12). Un
destino, id `sns-alertas`, el topic, sin transformador de entrada ni rol (EventBridge publica con la política del
topic). Cambiar el patrón es editar este bloque, `modules/observabilidad/main.tf`, `patron_esperado` y `CASOS_PATRON`
de `validate31.py` y `patron_bien()` de `tests/ops/falsos.py` en el mismo cambio. Cambiar la política del topic es editar
la tabla de §5.6, `data "aws_iam_policy_document" "alertas"` de `modules/observabilidad/main.tf`, `c1b_regla` de
`validate31.py` (exige `events.amazonaws.com` con una condición que nombre la regla, y `cloudwatch.amazonaws.com` o la
declaración de la cuenta) y `politica_bien()` de `tests/ops/falsos.py`, también en el mismo cambio.

### 5.11 Validadores de lotes (contrato común a las cuatro carpetas)

> Este contrato lo siguen las cuatro carpetas. Vive aquí porque infraestructura es dueña de la operación y del CI; el
> resto de documentos lo enlaza. Lo propio de cada carpeta (cómo encuentra el entorno, qué credenciales usa) está en el
> §5 de su ARCHITECTURE; el de esta carpeta, al final de esta sección.

**Correspondencia de nombres**

| Elemento | Forma | Ejemplo (lote BE-2.2) |
|---|---|---|
| Lote | `<PREFIJO>-<fase>.<n>`; la fase es siempre de un dígito | `BE-2.2` |
| Documento | `<CARPETA>/docs/validation/validation-<fase>-<n>.md` | `BACKEND_FASTAPI/docs/validation/validation-2-2.md` |
| Script | `<CARPETA>/project/src/ops/validate<fase><n>.py` | `BACKEND_FASTAPI/project/src/ops/validate22.py` |
| Ayudas de la carpeta | `<CARPETA>/project/src/ops/comun.py` | |

Un validador por lote (los diferidos no tienen hasta que se planifican). Las carpetas no comparten código de
validación: comparten este contrato.

**Contenido del documento de validación**, en este orden:
1. Encabezado: lote, script, entornos admitidos y criterios del PLAN que cubre.
2. **Precondiciones** (P1, P2…): lotes de esta u otras carpetas que deben estar «Hecho» y recursos que deben existir, y
   cómo las comprueba el script.
3. **Comprobaciones automáticas**: una o más por criterio automatizable, con el identificador del criterio en el PLAN
   (C1, C2…), qué hace el script y cuándo pasa. No repite el texto del criterio: lo enlaza.
4. **Comprobaciones manuales**: criterios que exigen a una persona (TalkBack, caminar, un correo recibido) y qué
   evidencia se deja en el PR.
5. **Datos de prueba y limpieza.**
6. **Cómo ejecutarlo**: comando y variables.

**Ejecución**
- Desde `<CARPETA>/project/`:
  `uv run --group ops python src/ops/validate<fase><n>.py --entorno {local|dev} [--informe RUTA] [--solo C1,C3]
  [--sin-limpieza]`.
- Un documento puede añadir argumentos propios del lote (por ejemplo, `--video` para indicar un recorrido real); el
  script los describe en `--help`.
- Python 3.12; las dependencias de los validadores van en el grupo `ops` del `pyproject.toml` de la carpeta (en la app
  y en infraestructura, un `pyproject.toml` solo para eso).
- `local` = servicios en la máquina (contenedores o dispositivo conectado); `dev` = AWS. Cada documento dice qué
  entornos admite. Un lote se cierra con la ejecución en `dev`, salvo que su documento diga otra cosa.
- Orden dentro del script: precondiciones → comprobaciones automáticas → lista de manuales → limpieza (siempre, también
  si algo falló, salvo `--sin-limpieza`) → informe.

**Estado de cada comprobación**: `pasa`, `falla`, `manual` (la hace una persona; el script imprime la instrucción) u
`omitida` (excluida con `--solo`).

**Códigos de salida**

| Código | Significado | Efecto en el §3 del PLAN |
|---|---|---|
| 0 | Todas las comprobaciones automáticas pasan (puede haber manuales pendientes) | El lote se puede cerrar cuando las manuales tienen evidencia |
| 1 | Al menos una comprobación falla | Sigue `En curso` |
| 2 | Una precondición no se cumple: otro lote no está listo | `Bloqueado` |
| 3 | Error de uso, de configuración o de credenciales | — |

**Informe**: una línea por comprobación en la salida estándar (`[PASA] C1 …`) y un JSON, por defecto en
`project/.validacion/<lote>-<AAAAMMDD-HHMMSS>.json` (carpeta ignorada por Git):
```json
{
  "lote": "BE-2.2", "validacion": "validation-2-2", "entorno": "dev", "commit": "a1b2c3d",
  "inicio": "2026-11-02T15:00:00Z", "fin": "2026-11-02T15:04:10Z",
  "resultado": "pasa",
  "precondiciones": [ { "id": "P1", "estado": "pasa", "detalle": "INF-2.1: horario configurado" } ],
  "comprobaciones": [ { "id": "C1", "estado": "pasa", "detalle": "3/3 fotos procesadas", "duracion_ms": 5321 } ],
  "manuales": [ { "id": "C3", "instruccion": "…" } ]
}
```
`resultado` ∈ {`pasa`, `falla`, `bloqueado`, `error`}, en correspondencia con los códigos 0 a 3. Una precondición que
falla porque faltan credenciales, herramientas o variables da **3**, no 2: el 2 es solo para «otro lote no está listo».

**Reglas**
- Los datos de prueba llevan siempre el prefijo `validacion-` en lo que el validador puede nombrar: nombres,
  `ref_cliente`, mensajes de alertas y las claves de S3 que escribe directamente (`dataset/validacion-…`, solo en los
  lotes de infraestructura). Lo que nombra el sistema (UUID del backend, `rec_NNNN` de la app) no cambia: el validador
  guarda qué creó y borra eso. Se borran al terminar. Un validador nunca modifica ni borra datos que no creó; los datos
  reales que usa (por ejemplo, un recorrido del campus) se quedan.
- Nunca imprime secretos, tokens ni URLs prefirmadas.
- Es idempotente: se puede repetir sin preparar nada a mano.
- Si un lote cambia sus criterios en el PLAN, su documento y su script se actualizan en el mismo cambio.
- **`embedding` en `dev`** (ADR-INF-14): un validador que necesita el servicio `embedding` en marcha (ingesta,
  localización) lo enciende si está apagado con el contrato de encendido de §5.10 (los de esta carpeta usan
  `embedding.Operador`) y espera hasta 10 min a que esté sano; poner `desiredCount = 1` sin más no basta (§3.4). Al
  terminar, también si algo falló, lo deja como lo encontró: lo apaga (como `embedding.py apagar`) solo si lo encendió él.
  Como a las 22:00 (`America/Bogota`) se apaga solo, cada validación declara la hora límite para empezar. El apagado
  por inactividad llega tras 45 min sin peticiones a `/v1/localize` ni mensajes en las colas: un validador que pase
  más tiempo sin usarlos vuelve a comprobar que `embedding` sigue encendido. Las tareas sueltas con la
  definición de `embedding` (validadores de embeddings) no necesitan el servicio: corren en Fargate por su cuenta.
- Por ahora se ejecutan desde la máquina de quien cierra el lote, con sus propias credenciales de AWS; ejecutarlos en CI
  es parte de INF-6.1.
- `validate13.py` (INF-1.3, anterior a esta regla) sube `embedding` con `update-service`: para repetirlo tras INF-2.1, se
  enciende antes con `embedding.py encender` (así lo encuentra en 1 y no lo toca) y se apaga después
  (`validation-1-3` §5).

**Recursos de apoyo que crea esta carpeta**
- **Imagen de prueba** (`project/pruebas/imagen-prueba/`): imagen mínima que responde 200 en `GET /v1/health` (puerto
  8000) y en `GET /health/ready` (puerto 8080), 404 en cualquier otro `GET` y 501 en los demás métodos (`POST` incluido).
  Se publica en los dos repositorios de ECR con la etiqueta `bootstrap`
  (la de `imagen_inicial_tag`), así los servicios pueden arrancar y validarse antes de que exista el código real. Su
  `ENTRYPOINT` ignora el comando de la definición de tarea, salvo si contiene `app.cli` (tareas `migrate`): en ese caso
  imprime `imagen de prueba: nada que migrar` y sale con 0. Con cualquier otro comando (`api`, `worker`, `embedding`)
  arranca el servidor de prueba en los dos puertos. La imagen trae `python` (los *health checks* de §5.7 lo usan) y corre
  con el usuario 10001. Se publica a mano, una vez, tras el `apply` de INF-1.3 (`pruebas/imagen-prueba/README.md`).
  Como la política de ECR conserva 5 imágenes, tras 5 despliegues reales `bootstrap` expira; solo hace falta volver a
  subirla si Terraform necesita crear una definición de tarea nueva antes de que CI despliegue.
- **Tarea de validación** `campus-locator-dev-validacion`: definición de tarea sin servicio, imagen pública
  `public.ecr.aws/docker/library/postgres:17-alpine` (trae `psql` y `nslookup`), con `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER` y `PGPASSWORD` (secreto `db`) y el grupo de seguridad `-api`. Los validadores la lanzan con
  `ecs run-task` sobrescribiendo el comando para comprobar cosas que solo se ven desde dentro de la VPC (base de datos,
  DNS de Cloud Map) y leen el resultado de `/campus-locator/dev/validacion`.

**Validadores de esta carpeta**
- Credenciales: el perfil de AWS de la persona (`AWS_PROFILE`), con lectura sobre la cuenta y escritura sobre los
  recursos de prueba (objetos `dataset/validacion-…`, mensajes en `ingesta` y, desde INF-3.1, en las DLQ, ejecución
  de la tarea de validación). El script se niega a correr si la cuenta no es `648617469176`.
- La tarea de validación también sirve para provocar una parada inocua (desde 0.15.0): `validate31.py` la lanza **sin
  `--group`** (queda `family:campus-locator-dev-validacion`), con `startedBy = validacion-3-1` (la rama de prueba de la
  regla, §5.10) y el comando de `app` sobrescrito a
  `["sh", "-c", "echo 'validacion-3-1: sale con error a proposito'; exit 3"]`, sin detener ningún servicio
  (ADR-INF-16). Escribe esa línea en `/campus-locator/dev/validacion` (stream `validacion/app/<id-de-la-tarea>`) y se
  detiene sola con `stopCode = EssentialContainerExited` y código 3 (comprobado en `dev` el 2026-10-26: 1,3 min desde el
  `run-task`). En 0.14.0
  la lanzaba con `--group service:worker`, que ECS rechaza («Invalid namespace for group.», §3.8). Ningún otro
  validador debe usar `startedBy = validacion-3-1`: su parada mandaría un correo.
- Lee los outputs con `terraform -chdir=bootstrap output -json` (lotes INF-0.x) y
  `terraform -chdir=envs/dev output -json` (el resto).
- Las comprobaciones sobre GitHub (INF-0.1 y INF-0.2) usan la CLI `gh` autenticada.
- Solo admiten el entorno `dev`.
- El campo `commit` del informe lleva `-dirty` si hay cambios sin commit en archivos versionados de `project/`.
- Leer las variables o configurar el entorno de un repositorio personal exige la cuenta de `gh` de su dueño (en una
  organización, un admin).

**Ayudas comunes (`project/src/ops/comun.py`).** Todo validador de esta carpeta las usa en vez de reimplementarlas; esta
tabla basta para escribir uno nuevo sin leer el código. Si cambian, la tabla se actualiza en el mismo cambio.

| Elemento | Qué hace |
|---|---|
| `Validador(lote=, validacion=, descripcion=, comprobaciones=[…], grupos={…})` (solo con nombre) | Ciclo de vida del validador. `comprobaciones` es la lista de IDs en orden (`["C1", "C2a", …]`; `--solo` rechaza cualquier otro); `grupos` son alias de `--solo` (p. ej. `{"C4": ["C4a", "C4b", "C4c"]}`). `v.correr(cuerpo)` lee los argumentos, rechaza un entorno que no sea `dev`, ejecuta `cuerpo(v)`, limpia, escribe el informe y devuelve el código; captura cualquier excepción como código 3 |
| `v.precondicion(id, fn)` → `bool` | Ejecuta `fn()`, que devuelve el texto del detalle. `Bloqueo` (o `Falla`) → código 2; `ErrorConfiguracion` o `ErrorGh` 401/403 → 3 |
| `v.precondicion_no_evaluada(id, motivo)`, `v.precondiciones_cumplidas()` | Marca las que dependen de una que falló; ¿pasaron todas? |
| `v.comprobacion(id, fn)` | `fn()` devuelve el detalle, como en `precondicion`. `omitida` si `--solo` la excluye; `Falla` → 1; `ErrorConfiguracion`, `ErrorGh` 401/403 o error imprevisto → 3. Mide `duracion_ms` |
| `v.incluida(id)`, `v.alguna_incluida(*ids)` | Para no crear datos de prueba que ninguna comprobación incluida usará |
| `v.manual(id, instruccion)` | Comprobación manual (estado `manual`) |
| `v.al_limpiar(descripcion, fn)` | Registra una limpieza; se ejecutan en orden inverso al terminar, también si algo falló, salvo con `--sin-limpieza` |
| `v.sello` | `AAAAMMDD-HHMMSS` (UTC) del inicio, para nombrar los datos `validacion-…` |
| `Falla`, `Bloqueo`, `ErrorConfiguracion`; `ErrorGh` (hereda de `Falla`; `.http`, `.sin_permiso`, `.resultado`) | Excepciones que deciden el código |
| `ejecutar(comando, entrada=, timeout=300)` → `Resultado` | `comando` es una lista. Ejecuta un programa desde `project/` sin imprimir nada, con el entorno de `_entorno_proceso()` (`TF_IN_AUTOMATION`, `TF_INPUT=0`, `NO_COLOR`, sin paginadores de `gh` ni de `aws`); si no está instalado → `ErrorConfiguracion`. `Resultado` es un *dataclass* `(codigo, salida, error)` con la propiedad `texto` (salida y error juntos) |
| `gh(*args)` → `str`; `gh_api(ruta, metodo=, cuerpo=, paginar=, jq=)` | CLI `gh`; `gh_api` devuelve el JSON (o el texto de `jq`) y lanza `ErrorGh` si falla |
| `terraform_outputs(directorio)` → `dict`; `terraform_state_pull(directorio)` → `dict` | `terraform -chdir=…`; sin `init` o sin credenciales → `ErrorConfiguracion`. El estado nunca se imprime |
| `sesion_aws()`; `comprobar_cuenta(sesion)` → ARN | boto3 en `us-east-1` con `AWS_PROFILE`; `comprobar_cuenta` devuelve el ARN de quien llama y se niega a seguir si la cuenta no es `648617469176` |
| `errores_aws(accion)` (bloque `with`), `error_aws(exc, accion)`, `codigo_error_aws(exc)` | Traducen errores de boto3: permisos o credenciales → `ErrorConfiguracion` (`"<accion>: las credenciales no tienen permiso (<código>: <mensaje>)"`); el resto → `Falla` (`"<accion>: <código>: <mensaje>"`). Desde 0.15.0 el texto lleva `Error.Message` de AWS además del código (sin él, o si repite el código, solo el código), en una línea, recortado a 300 caracteres y con «…» en lugar de los IDs de llaves de acceso (`AKIA…`/`ASIA…`) y de los parámetros `X-Amz-Signature`, `X-Amz-Credential` y `X-Amz-Security-Token` de una URL prefirmada (función interna `_mensaje_error_aws`). Un error sin código (red, credenciales locales) → `ErrorConfiguracion` con el texto de la excepción, con la misma limpieza |
| `LectorCola(sqs, url, nombre, clasificar, ocultar_s=120)` (desde INF-3.1; antes estaba en `validate21.py`) | Borra de una cola los mensajes de prueba sin estropear los ajenos. `clasificar(cuerpo)` → `"propio"`, `"resto"` (de otra ejecución ya abandonada) o `"ajeno"`. `leer(segundos, objetivo=None)` recibe de 10 en 10 (espera larga de 2 s, visibilidad `ocultar_s`) hasta que pasen `segundos`, haya borrado `objetivo` o una lectura venga vacía; borra propios y restos (`DeleteMessageBatch`) y deja ocultos los ajenos; `devolver()` los hace visibles con visibilidad 0 (no lanza excepciones: sirve al limpiar). Así cada ajeno se recibe como mucho una vez por lectura (cuenta para el `maxReceiveCount` de su cola). Atributos `borrados` y `ajenos`. Errores como `errores_aws` |
| `avisar(mensaje)`, `resumir(texto, limite)`, `commit_actual()` | Progreso a stderr (stdout queda para `[PASA] …`); recorte de mensajes; commit con `-dirty` |
| `CUENTA`, `REGION`, `PROYECTO`, `DIR_INFORMES` | Constantes (`PROYECTO` y `DIR_INFORMES` son rutas: `project/` y `project/.validacion/`) |
| `PATRON_CREDENCIALES_TERRAFORM`, `PATRON_SIN_INIT` | Expresiones regulares que reconocen en la salida de Terraform un fallo de credenciales (→ código 3) o una copia sin `init` |

Forma de un validador (`validate01.py` la sigue; `validate11.py` es el ejemplo más corto, de solo lectura, y
`validate12.py` el de uno que crea datos de prueba —objetos y mensajes— y los limpia con `al_limpiar`): `import comun`
(el script se ejecuta como `python src/ops/validate<fase><n>.py`), `main()` crea el `Validador` y devuelve
`correr(cuerpo)`, y el módulo termina con `sys.exit(main())`. `cuerpo(v)`
evalúa primero las precondiciones de credenciales (código 3), luego las de otros lotes (código 2), sin seguir si alguna
falla; limpia restos `validacion-…` de ejecuciones anteriores; registra con `al_limpiar` lo que cree, en cuanto lo crea,
y ejecuta las comprobaciones en el orden del documento de validación.

**Encendido de `embedding` desde un validador (`project/src/ops/embedding.py`, INF-2.1).** `import embedding` y
`Operador(sesion)` (sesión ya comprobada con `comun.comprobar_cuenta`): `encender(esperar=True, limite_s=600)` y
`apagar(esperar=True)` siguen el contrato de §5.10 y devuelven los segundos que tardaron; `sano()` → `(bool, lo que
falta)`; `servicio(nombre)`, `objetivo(nombre)`, `alarma(nombre)`, `cola("ingesta"|"purga")` (visibles, en vuelo,
retrasados) y `acciones_noche()` leen; `registrar(nombre, maximo)` y `poner(nombre, replicas)` cambian el rango o
`desiredCount`; `t_latido` es el momento de la última muestra de `EmbeddingEncendidos`. Lanza `comun.Bloqueo` si falta
INF-1.3 o INF-2.1 y traduce los errores de AWS como `comun.errores_aws`. `validate21.py` es el ejemplo. Del módulo
también se usan (`validate21.py` y `validate31.py`): las constantes `PREFIJO` y `CLUSTER` (`campus-locator-dev`),
`COLAS` (`ingesta`/`purga` → nombre) y `ESCALADOS`; `recurso(servicio)` → `service/campus-locator-dev/<servicio>`;
`llamar(accion, fn, *codigos_ausente)`, que ejecuta `fn()` dentro de `comun.errores_aws(accion)` y devuelve `None` si
el error es uno de `codigos_ausente`; y `hora_bogota(momento=None)`, la hora en `America/Bogota` (UTC−5 si falta la
base de zonas).

**Pruebas locales de los validadores (`project/tests/ops/`, desde INF-3.1).** `uv run --group ops --group pruebas
pytest tests/ops -q` desde `project/` (el grupo `pruebas` del `pyproject.toml` trae pytest; `pythonpath = src/ops`).
No tocan AWS: `tests/ops/falsos.py` es un AWS falso con reloj falso que otro validador puede extender:

| Elemento de `falsos.py` | Qué hace |
|---|---|
| `Mundo()` | Estado (alarmas, historia de alarmas, regla, destinos, política del topic, suscripciones, colas, tareas, métricas) y reloj. `dormir(s)` avanza de 5 en 5 s y simula: una DLQ con mensajes visibles pasa su alarma a `ALARM` tras `retraso_alarma` s (y vuelve a `OK` vacía); el paso a `ALARM` escribe las entradas `StateUpdate` y `Action` y publica en el topic; una tarea se detiene a los `dura_tarea` s con `stop_code` y, si casa con el patrón de la regla, cuenta `MatchedEvents` e `Invocations` (o `FailedInvocations` sin permiso en la política) y publica; SNS entrega si la suscripción no está `pendiente`. Las métricas aparecen a los `retraso_metricas` s |
| Interruptores del `Mundo` | `retraso_alarma`, `alarma_dispara`, `accion_ok`, `retraso_metricas`, `pendiente`, `stop_code`, `dura_tarea`, `run_task_falla` (código de error de `run_task`), `cuenta`, y los datos `apis`, `acciones_noche`, `alarmas`, `regla`, `destinos`, `politica`, `suscripciones`, `colas` (URL → mensajes). Como ECS en `dev`, `run_task` rechaza siempre un `group` que empiece por `service:` (`InvalidParameterException` «Invalid namespace for group.»); sin `group`, la tarea queda en `family:<definición>` |
| `Sesion(mundo)` / `Reloj(mundo)` | Sustitutos de la sesión de boto3 (clientes falsos de `sts`, `apigatewayv2`, `application-autoscaling`, `cloudwatch`, `events`, `sns`, `sqs` y `ecs`, solo con las operaciones que usan los validadores) y del módulo `time` (`monotonic`, `sleep`) |
| `alarmas_bien()`, `politica_bien()`, `patron_bien()`, `patron_0_14()`, `salidas(**cambios)` | Lo que deja el `apply` de INF-3.1 (`patron_bien`, el patrón de 0.15.0 con `$or`; `patron_0_14`, el de 0.14.0, para probar un patrón viejo) y los outputs de `envs/dev` (con `None`, un output falta). Duplican §5.10 y §5.6: se cambian con ellos (§5.10) |
| Registro | `enviados` (`(url, cuerpo)`), `borrados` (cuerpos), `run_task_args` (argumentos de cada `run_task`), `tareas` (ARN → tarea) |
| Constantes y ayudas | `CUENTA`, `REGION`, `P` (`campus-locator-dev`), `TOPIC_ARN`, `REGLA`, `REGLA_ARN`, `CLUSTER_ARN`, `API_ID` (`fuzq99kddb`), `URL_COLA` (prefijo de las URL de SQS), `CORREO` (`persona@example.com`); `error(codigo, operacion, mensaje=None)` crea un `ClientError` de boto3 (con `Error.Message` = `mensaje` o, sin él, el código); `coincide(patron, evento)` evalúa un patrón de EventBridge de listas, objetos anidados y `$or` (lo usan la regla falsa al detener una tarea y `events.test_event_pattern`, que además exige los campos obligatorios del evento: `id`, `account`, `source`, `time`, `region`, `resources`, `detail-type`). El reloj del `Mundo` empieza el 2026-10-28 a las 15:00 UTC (`t`) con `mono = 1000` |
| Límites (lo que no simula) | Sin paginación (`NextToken` se ignora); `get_metric_statistics` solo casa las dimensiones exactas y agrega por minuto con `Sum`, `Maximum`, `Minimum` o `SampleCount`; SQS ignora `WaitTimeSeconds` y recibir no avanza el reloj; el único esperador de ECS es `tasks_stopped`; `stop_task` deja `stopCode = UserInitiated`; las alarmas solo cambian las de las DLQ (por mensajes visibles); el `group` de `run_task` solo se valida por el prefijo `service:` |

Las pruebas parchean con `monkeypatch` `comun.time`, `validate31.time`, `comun.ahora_utc`, `comun.sesion_aws`,
`comun.commit_actual`, `comun.terraform_outputs` y `validate31.leer_correo`, y corren `validate31.main()` con
`--informe` en un directorio temporal. En `test_validate31.py`, el *fixture* `mundo` hace esos parches y deja los
outputs en `mundo.salidas`; `correr(mundo, monkeypatch, *argumentos)` → `(código, informe)`; `estados(informe)` →
`{id: estado}` de precondiciones y comprobaciones; `detalle(informe, id)`; `cuerpo_propio(sello)`. `test_comun.py`
prueba `comun.LectorCola` y su uso desde `validate21.py`. Trampa: `import falsos` funciona porque pytest añade
`tests/ops/` a `sys.path` al importar pruebas sin `__init__.py`; si se añade un `__init__.py`, hay que cambiar los
imports (o añadir `tests/ops` a `pythonpath`). Los validadores anteriores a INF-3.1 se probaron con simulaciones que
no están en el repositorio (CHANGELOG de cada uno).

Lint de los validadores y sus pruebas (no lo corre CI): `uvx ruff@0.14.0 check --line-length 120 src/ops tests/ops`
desde `project/`, sin avisos. Las líneas del código de esta carpeta llegan hasta 120 columnas.

Desde la consola: `uv run --group ops python src/ops/embedding.py {encender|apagar|estado}` (desde `project/`, con
`AWS_PROFILE`; `--sin-esperar` en `encender` y `apagar` no espera a que quede sano o sin tareas, aunque `encender`
sí espera a la alarma). Comprueba la cuenta como los validadores. Códigos de salida: 0 hecho; 1 no quedó como se
pedía en el tiempo de espera (10 min hasta sano, 10 min sin tareas o 5 min a la alarma); 2 falta un lote (INF-1.3 o
INF-2.1 sin aplicar: no crea objetivos escalables ni alarmas); 3 credenciales, permisos o uso. El progreso va a stderr
y el resultado a stdout; no imprime secretos. `estado` solo lee: servicios, rango de cada objetivo, estado de las
cuatro alarmas, mensajes de las dos colas y acciones nocturnas.

### 5.12 Código de Terraform de `envs/dev` y de los módulos (convenciones)

Lo que un lote necesita saber para añadir infraestructura sin leer el código existente (INF-0.2 dejó el esqueleto).

**Archivos de `envs/dev`**

| Archivo | Contiene | Regla |
|---|---|---|
| `backend.tf` | *backend* S3 (§3.9): bucket `campus-locator-tfstate-648617469176`, clave `dev/terraform.tfstate`, `use_lockfile`, `encrypt`, `allowed_account_ids` | No se toca |
| `providers.tf` | `terraform { required_version = ">= 1.10" }`, `required_providers` (`hashicorp/aws ~> 6.70` y, desde INF-1.2, `hashicorp/random ~> 3.7`) y `provider "aws"` (`region = var.region`, `allowed_account_ids = [var.aws_account_id]`, `default_tags`) | Un proveedor nuevo se declara aquí (ver «Proveedores y lock») |
| `main.tf` | Solo `data` (cuenta, etiquetas y, desde INF-1.3, los outputs de `bootstrap`) y las llamadas a los seis módulos | Ningún recurso suelto: todo recurso vive en un módulo |
| `variables.tf` / `terraform.tfvars` | Variables de §5.3 que ya usa algún lote, con `type` y `description`; sus valores | Una variable nueva se añade a §5.3 y a los dos archivos en el mismo cambio |
| `outputs.tf` | Outputs de §5.2 | Un output nuevo se añade antes a §5.2 |
| `.terraform.lock.hcl` | Versiones y *hashes* de los proveedores | Versionado; ver «Proveedores y lock» |
| `.gitignore` | Ignora `.terraform/` y los planes; reincluye el lock y `terraform.tfvars` | — |

**Nombres que ya existen en `envs/dev`**

| Nombre | Qué es |
|---|---|
| `var.aws_account_id`, `var.region`, `var.proyecto`, `var.entorno`; `var.cidr_vpc`, `var.az_computo`, `var.az_secundaria` (INF-1.1); `var.rds_clase`, `var.rds_gb`, `var.rds_gb_max`, `var.pg_version` (INF-1.2); `var.imagen_inicial_tag` (INF-1.3); `var.apagado_embedding` (INF-2.1); `var.correo_alertas` (INF-3.1) | Variables de §5.3 (`aws_account_id` se valida como 12 dígitos; `correo_alertas`, como dirección de correo) |
| `local.prefijo` | `"${var.proyecto}-${var.entorno}"` = `campus-locator-dev`, sin guion final: el prefijo de §5.1. Está en `main.tf` (INF-1.1); los módulos lo reciben como variable `prefijo` |
| `local.metrica_localize` | `{ espacio = "${var.proyecto}/${var.entorno}", nombre = "LocalizePeticiones" }` (INF-2.1): la métrica del filtro de `borde`, que lee la alarma de inactividad de `computo`. Se define aquí y se pasa a los dos módulos, así ninguno referencia al otro por ella |
| `data.aws_caller_identity.actual` | Cuenta de las credenciales (`.account_id`); alimenta el output `cuenta_id` |
| `data.terraform_remote_state.bootstrap` | Outputs de `bootstrap` (backend S3, clave `bootstrap/terraform.tfstate` del bucket de estado; los dos roles de CI pueden leer todo el bucket). Hoy solo se usa `.outputs.limite_roles_arn` (INF-1.3) |
| `data.aws_default_tags.actuales` | Etiquetas efectivas del proveedor; nada lo referencia (lleva `# tflint-ignore: terraform_unused_declarations`) porque solo sirve para que los validadores lean las etiquetas del estado |
| `module.red`, `module.datos`, `module.secretos`, `module.computo`, `module.borde`, `module.observabilidad` | Llamadas a `../../modules/<nombre>`. `module.red` recibe `prefijo`, `region`, `cidr_vpc`, `az_computo` y `az_secundaria` (INF-1.1); `module.datos`, `module.secretos` y `module.computo`, lo que dicen sus tablas más abajo (INF-1.2, INF-1.3); `module.borde`, lo que dice su tabla más abajo (INF-1.4); desde INF-2.1, `module.computo` recibe además `metrica_localize` y `apagado_embedding`, y `module.borde`, `metrica_localize`; `module.observabilidad` (INF-3.1), lo que dice su tabla más abajo |
| Outputs de `envs/dev` | `cuenta_id` (INF-0.2); `subredes_tareas` = `[module.red.subred_tareas]` y `sg_migrate` = `module.red.grupos_seguridad["api"]` (INF-1.1); `bucket_dataset`, `sqs_ingesta_url`, `sqs_purga_url`, `sqs_ingesta_dlq_url` y `sqs_purga_dlq_url` (de `module.datos.colas[…].url`), `rds_endpoint` = `module.datos.rds_direccion` y `secretos` = `module.secretos.arns` (INF-1.2); `ecr_backend_url` y `ecr_embedding_url` (de `module.computo.ecr_urls[…]`), `ecs_cluster`, `ecs_servicios`, `familias_tarea` y `embedding_dns` (INF-1.3); `api_base_url` = `module.borde.api_base_url` (INF-1.4); `sns_alertas_arn` = `module.observabilidad.sns_alertas_arn` (INF-3.1) |
| Última línea de `main.tf`: `# validacion-0-2 <AAAAMMDD-HHMMSS>` | La escribe y sustituye `validate02.py` (C2 la fusiona en `main`). No se borra ni hace falta moverla: el validador quita la anterior y añade la nueva al final |

**Módulos (`modules/<nombre>/`)**
- Cada uno tiene `main.tf` y `versions.tf` (`terraform { required_version = ">= 1.10" }`); un módulo grande puede
  repartir sus recursos en más archivos por tema (`computo/escalado.tf`, INF-2.1). Cuando un módulo usa un
  proveedor, lo declara en `required_providers` de su `versions.tf` con la misma restricción que `envs/dev`.
- Entradas en `variables.tf` (siempre con `type` y `description`) y salidas en `outputs.tf`. Un módulo nunca llama a
  otro: `main.tf` de `envs/dev` pasa los outputs de uno como entradas de otro.
- Las cuatro etiquetas de §5.1 las pone el proveedor (`default_tags`): los recursos no las repiten; solo añaden las
  propias (`Name` u otras de su lote).

**Módulo `red` (INF-1.1)** — lo que los lotes siguientes necesitan para usarlo sin leer su código.

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `prefijo` | `string` | `local.prefijo` |
| `region` | `string` | `var.region` (forma `com.amazonaws.<region>.s3`) |
| `cidr_vpc` | `string`; si no es una /16, falla la validación de la variable | `var.cidr_vpc` |
| `az_computo`, `az_secundaria` | `string` | `var.az_computo`, `var.az_secundaria` |

| Salida | Valor | La usa |
|---|---|---|
| `vpc_id` | ID de `campus-locator-dev-vpc` | quien necesite la VPC (p. ej. el *namespace* privado de Cloud Map, INF-1.3) |
| `subred_tareas` | ID de `publica-a` (`string`) | `computo` (servicios y tareas de Fargate, INF-1.3); output `subredes_tareas` |
| `subredes_publicas` | `[publica-a, publica-b]` (IDs, en ese orden) | `borde` (VPC Link, INF-1.4) |
| `subredes_privadas` | `[privada-a, privada-b]` (IDs, en ese orden) | `datos` (grupo de subredes de RDS, INF-1.2) |
| `grupos_seguridad` | mapa `{ vpclink, api, worker, embedding, rds }` → ID | `datos` (`rds`), `computo` (`api`, `worker`, `embedding`), `borde` (`vpclink`); output `sg_migrate` (`api`) |

Ejemplo de cómo lo consume un lote posterior (INF-1.2), en `envs/dev/main.tf`:
```hcl
module "datos" {
  source = "../../modules/datos"

  subredes_privadas = module.red.subredes_privadas
  sg_rds            = module.red.grupos_seguridad["rds"]
}
```
Por dentro (para leer un `plan`): `aws_vpc.principal`, `aws_subnet.subredes["publica-a"|"publica-b"|"privada-a"|"privada-b"]`,
`aws_internet_gateway.principal`, `aws_route_table.publica` y `.privada`, `aws_route.publica_internet`,
`aws_route_table_association.subredes[…]`, `aws_vpc_endpoint.s3`, `aws_default_security_group.default`,
`aws_security_group.grupos["vpclink"|"api"|"worker"|"embedding"|"rds"]` y las reglas
`aws_vpc_security_group_ingress_rule.entradas[…]`, `aws_vpc_security_group_egress_rule.vpclink_a_api` y
`aws_vpc_security_group_egress_rule.salida_libre[…]`: 29 recursos. Las tablas no llevan bloques `route` en línea (una
ruta nueva es un `aws_route`) y los grupos tampoco llevan reglas en línea (§5.7).

**Módulo `datos` (INF-1.2)**

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `prefijo` | `string` | `local.prefijo` |
| `cuenta_id` | `string` de 12 dígitos | `var.aws_account_id` (sufijo del bucket y `aws:SourceAccount` de la política de `ingesta`) |
| `az_computo` | `string` | `var.az_computo` |
| `subredes_privadas` | `list(string)`, exactamente dos | `module.red.subredes_privadas` |
| `sg_rds` | `string` | `module.red.grupos_seguridad["rds"]` |
| `rds_clase`, `rds_gb`, `rds_gb_max`, `pg_version` | `string`, `number`, `number` (> `rds_gb`), `string` de solo dígitos | las variables de §5.3 del mismo nombre |
| `db_password` | `string`, `sensitive` | `module.secretos.db_password` |

| Salida | Valor | La usa |
|---|---|---|
| `rds_direccion` | endpoint sin puerto | `secretos` (`db_host`); output `rds_endpoint`; `computo` (`DB_HOST`, INF-1.3) |
| `rds_identificador` | `campus-locator-dev-db` (`identifier` de la instancia; desde INF-3.1) | `observabilidad` (dimensión `DBInstanceIdentifier` de las alarmas de RDS) |
| `rds_puerto`, `rds_base`, `rds_usuario` | `5432`, `campus_locator`, `campus_app` | `secretos`; `computo` (`DB_PORT`, `DB_NAME`, `DB_USER`) |
| `bucket_dataset`, `bucket_dataset_arn` | nombre y ARN del bucket | output `bucket_dataset`; `computo` (`S3_BUCKET_DATASET` y políticas de §5.8) |
| `colas` | mapa `{ ingesta, purga, ingesta_dlq, purga_dlq }` → `{ nombre, url, arn }` | outputs `sqs_*_url`; `computo` (`SQS_URL_*` y políticas de §5.8; alarmas de INF-2.1, `nombre`); `observabilidad` (alarmas de las DLQ, `nombre`, INF-3.1) |

Por dentro: `aws_db_subnet_group.principal`, `aws_db_parameter_group.principal` (con `create_before_destroy`),
`aws_db_instance.principal`, `aws_s3_bucket.dataset` y sus `aws_s3_bucket_ownership_controls`,
`aws_s3_bucket_public_access_block`, `aws_s3_bucket_server_side_encryption_configuration`,
`aws_s3_bucket_lifecycle_configuration`, `aws_s3_bucket_policy` y `aws_s3_bucket_notification` (todos `.dataset`),
`aws_sqs_queue.colas["ingesta"|"purga"]`, `aws_sqs_queue.dlq["ingesta"|"purga"]` y `aws_sqs_queue_policy.ingesta`:
15 recursos, más dos `data "aws_iam_policy_document"` (`dataset` e `ingesta`). La notificación depende de la política
de la cola y de la del bucket (S3 rechaza dos cambios de configuración a la vez sobre el mismo bucket). `rds.force_ssl`
se declara con `apply_method = "pending-reboot"`: en PostgreSQL 17 su valor `1` ya es el de por defecto, RDS lo lista
como `Source = system` con ese método y, con el `immediate` por defecto del proveedor, el `plan` nunca quedaría vacío.

**Módulo `secretos` (INF-1.2)**

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `ruta` | `string` `<proyecto>/<entorno>` | `"${var.proyecto}/${var.entorno}"` |
| `db_host`, `db_puerto`, `db_nombre`, `db_usuario` | `string`, `number`, `string`, `string` | `module.datos.rds_direccion`, `.rds_puerto`, `.rds_base` y `.rds_usuario` |
| `admin_inicial_correo` | `string` | `"admin@campus.edu.co"` (§5.4) |

| Salida | Valor | La usa |
|---|---|---|
| `db_password` | contraseña de la base (`sensitive`) | `datos` |
| `arns` | mapa `{ db, jwt, admin_inicial }` → ARN | output `secretos`; `computo` (rol de ejecución y `secrets` de las definiciones de tarea, INF-1.3) |

Por dentro: `random_password.db`, `random_bytes.jwt`, `random_password.admin_inicial`,
`aws_secretsmanager_secret.secretos["db"|"jwt"|"admin_inicial"]` y `aws_secretsmanager_secret_version.db`, `.jwt` y
`.admin_inicial`: 9 recursos. Para rotar un valor (ADR-INF-07) se reemplaza su recurso `random_*`; la contraseña de
`db` la toman RDS y el secreto en el mismo `apply`, y las tareas al reiniciarse.

**Módulo `computo` (INF-1.3)**

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `prefijo`, `proyecto`, `entorno`, `region` | `string` | `local.prefijo`, `var.proyecto`, `var.entorno`, `var.region` |
| `cuenta_id` | `string` de 12 dígitos | `var.aws_account_id` (`aws:SourceAccount` de la confianza de los roles) |
| `vpc_id`, `subred_tareas` | `string` | `module.red.vpc_id`, `module.red.subred_tareas` |
| `grupos_seguridad` | `map(string)` con `api`, `worker` y `embedding` | `module.red.grupos_seguridad` |
| `limite_roles_arn` | `string` | `data.terraform_remote_state.bootstrap.outputs.limite_roles_arn` |
| `secretos` | `map(string)` con `db`, `jwt` y `admin_inicial` | `module.secretos.arns` |
| `db_host`, `db_puerto`, `db_nombre`, `db_usuario` | `string`, `number`, `string`, `string` | `module.datos.rds_direccion`, `.rds_puerto`, `.rds_base`, `.rds_usuario` |
| `bucket_dataset`, `bucket_dataset_arn` | `string` | `module.datos.bucket_dataset`, `.bucket_dataset_arn` |
| `colas` | mapa de `{ nombre, url, arn }` con `ingesta` y `purga` | `module.datos.colas` |
| `imagen_inicial_tag` | `string` | `var.imagen_inicial_tag` |
| `metrica_localize` | `object({ espacio = string, nombre = string })` | `local.metrica_localize` (INF-2.1; su `espacio` es también el de `EmbeddingEncendidos`) |
| `apagado_embedding` | `object({ zona = string, noche = optional(string), inactividad_min = number })`; `noche` debe ser `null` o `cron(...)` e `inactividad_min` un entero entre 5 y 1440 (si no, falla la validación) | `var.apagado_embedding` (INF-2.1) |

| Salida | Valor | La usa |
|---|---|---|
| `ecr_urls` | `{ backend, embedding }` → `repositoryUri` | outputs `ecr_backend_url` y `ecr_embedding_url` |
| `cluster` | `campus-locator-dev` | output `ecs_cluster`; `observabilidad` (dimensión `ClusterName`) |
| `cluster_arn` | `arn:aws:ecs:us-east-1:648617469176:cluster/campus-locator-dev` (desde INF-3.1) | `observabilidad` (`clusterArn` del patrón de la regla) |
| `servicios` | `{ api, worker, embedding }` → nombre | output `ecs_servicios`; `observabilidad` (`group` de la regla, `ServiceName` de la alarma de `embedding`) |
| `familias_tarea` | `{ api, worker, embedding, migrate, validacion }` → familia | output `familias_tarea` |
| `embedding_dns` | `embedding.campus-locator.local` | output `embedding_dns` |
| `cloud_map_api_arn` | ARN del servicio de Cloud Map `api` (SRV) | `borde` (`integration_uri`, INF-1.4) |

Por dentro: `aws_ecr_repository.repos["backend"|"embedding"]` y `aws_ecr_lifecycle_policy.repos[…]`,
`aws_ecs_cluster.principal`, `aws_service_discovery_private_dns_namespace.principal`,
`aws_service_discovery_service.servicios["api"|"embedding"]`,
`aws_cloudwatch_log_group.procesos["api"|"worker"|"embedding"|"migrate"|"validacion"]`, `aws_iam_role.ejecucion`,
`aws_iam_role_policy_attachment.ejecucion`, `aws_iam_role_policy.ejecucion_secretos`,
`aws_iam_role.tareas["api"|"worker"|"embedding"|"migrate"]`, `aws_iam_role_policy.tarea_api` y `.tarea_worker`,
`aws_ecs_task_definition.tareas[…]` (las cinco familias) y `aws_ecs_service.servicios["api"|"worker"|"embedding"]`:
30 recursos, más cuatro `data "aws_iam_policy_document"`. Detalles que explican un `plan`:
- Las definiciones de tarea solo envían las claves que aplican (sin `null` ni listas vacías), con `environment` y
  `secrets` ordenados por nombre y `hostPort` = `containerPort`: así ECS devuelve lo mismo y el `plan` queda vacío.
- `api` no fija `command` (usa el `CMD` de la imagen); `worker` y `migrate` llevan los de `BACKEND_FASTAPI` §5.9;
  `embedding`, el `CMD` de su imagen (`SERVICE_EMBEDDING` §5.5). La tarea de validación tiene un comando inocuo que los
  validadores sobrescriben y usa el rol de tarea de `migrate`.
- Cloud Map sin `health_check_custom_config`: las instancias que registra ECS cuentan como sanas y ECS las quita al
  detener la tarea. `api` se registra con `container_name = "app"` y `container_port = 8000` (lo exige el SRV).
- Servicios con `availability_zone_rebalancing = "DISABLED"` (una zona), *circuit breaker* con *rollback*,
  `assign_public_ip = true` y `ignore_changes = [task_definition, desired_count]` (ADR-INF-09).

`escalado.tf` (INF-2.1, ADR-INF-15) añade 11 recursos (41 en total): `aws_appautoscaling_target.servicios["embedding"|"worker"]`,
`aws_appautoscaling_policy.worker_cola`, `.worker_colas_vacias` y `.embedding_apagar`,
`aws_cloudwatch_metric_alarm.worker_cola["ingesta"|"purga"]`, `.worker_colas_vacias` y `.embedding_inactivo`, y
`aws_appautoscaling_scheduled_action.noche["embedding"|"worker"]` (ninguna si `apagado_embedding.noche` es `null`).
Detalles que explican un `plan` o un comportamiento:
- Los objetivos se crean con rango 0-0 e ignoran `min_capacity` y `max_capacity` (como `desired_count`, ADR-INF-09):
  los cambian `embedding.py` y las acciones de las 22:00, y un `plan` no los devuelve a 0-0.
- Políticas `StepScaling` con `ExactCapacity` y enfriamiento de 60 s, una por sentido (`worker-cola` → 1;
  `worker-colas-vacias` y `embedding-apagar` → 0). Cada una tiene dos pasos, `(−∞, 0]` y `[0, ∞)`, con la misma
  capacidad: da igual qué muestras agregue Application Auto Scaling (con `FILL`, la más reciente suele valer 0 aunque
  la alarma esté en `ALARM`). Los límites van como cadena (`"0"`, como los guarda el proveedor).
- Las políticas de un mismo objetivo y las acciones programadas se crean una tras otra (`depends_on`): Application
  Auto Scaling puede rechazar cambios simultáneos sobre un objetivo y el proveedor no los reintenta.
- Las alarmas son de expresión, con umbral 0,5 sobre valores que son 0 o enteros positivos: la distancia al umbral
  (lo que comparan los pasos) nunca es 0. `FILL(m, 0)` da 0 donde una métrica no tiene dato (SQS no publica de una
  cola inactiva; `LocalizePeticiones` solo existe con peticiones) y `+ 0 * <cpu del servicio>` no cambia el valor pero
  asegura un dato por minuto mientras el servicio corre. Las métricas de las expresiones no llevan `return_data` (el
  proveedor lo guarda como `false`, igual que AWS).
- Las alarmas no avisan a nadie (INF-3.1 añade las que van al topic); su única acción es la política.

Alarmas de `escalado.tf`, tal como quedan en AWS. Todas tienen umbral 0,5, `treat_missing_data = notBreaching` y
métricas de 60 s. Ids de las métricas: `embedding` y `worker` = `AWS/ECS` `CPUUtilization` `SampleCount` con
`ClusterName = campus-locator-dev` y `ServiceName = <servicio>`; `visibles` e `ingesta_visibles`/`purga_visibles` =
`AWS/SQS` `ApproximateNumberOfMessagesVisible` `Maximum` con `QueueName` de la cola; `ingesta_en_vuelo` y
`purga_en_vuelo` = `ApproximateNumberOfMessagesNotVisible` `Maximum`; `localize` = `campus-locator/dev`
`LocalizePeticiones` `Sum`; `encendidos` = `campus-locator/dev` `EmbeddingEncendidos` `Sum`.

| Alarma | Expresión (id que devuelve datos) | Comparación · M de N | Acción |
|---|---|---|---|
| `campus-locator-dev-worker-cola-ingesta` y `-worker-cola-purga` (`for_each` sobre la cola) | `subir` = `(FILL(embedding, 0) > 0) AND (FILL(visibles, 0) >= 1)` | `GreaterThanThreshold` · 1 de 10 | `campus-locator-dev-worker-cola` (→ 1) |
| `campus-locator-dev-worker-colas-vacias` | `mensajes` = `FILL(ingesta_en_vuelo, 0) + FILL(ingesta_visibles, 0) + FILL(purga_en_vuelo, 0) + FILL(purga_visibles, 0) + 0 * worker` | `LessThanThreshold` · 15 de 15 | `campus-locator-dev-worker-colas-vacias` (→ 0) |
| `campus-locator-dev-embedding-inactivo` | `uso` = `FILL(localize, 0) + FILL(encendidos, 0) + <la suma de las cuatro colas> + 0 * embedding` | `LessThanThreshold` · `inactividad_min` de `inactividad_min` | `campus-locator-dev-embedding-apagar` (→ 0) |

Cambiar una alarma es editar esta tabla, `escalado.tf` y las comprobaciones C2a/C3a de `validate21.py` en el mismo
cambio. Con 7 métricas, la de inactividad está cerca del máximo de 10 por alarma de expresión.

**Módulo `borde` (INF-1.4)**

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `prefijo`, `proyecto`, `entorno` | `string` | `local.prefijo`, `var.proyecto`, `var.entorno` (nombres de §5.1 y ruta del *log group*) |
| `subredes_publicas` | `list(string)`, exactamente dos | `module.red.subredes_publicas` |
| `sg_vpclink` | `string` | `module.red.grupos_seguridad["vpclink"]` |
| `cloud_map_api_arn` | `string` | `module.computo.cloud_map_api_arn` |
| `metrica_localize` | `object({ espacio = string, nombre = string })` | `local.metrica_localize` (INF-2.1) |

| Salida | Valor | La usa |
|---|---|---|
| `api_base_url` | `ApiEndpoint` de la API (`https://<id>.execute-api.us-east-1.amazonaws.com`, sin barra final) | output `api_base_url` |
| `api_id` | `ApiId` de la API (`fuzq99kddb`; desde INF-3.1) | `observabilidad` (dimensión `ApiId` de la alarma de 5xx) |

Por dentro: `aws_cloudwatch_log_group.apigw`, `aws_apigatewayv2_vpc_link.principal`, `aws_apigatewayv2_api.principal`
(con `prevent_destroy`), `aws_apigatewayv2_integration.api`, `aws_apigatewayv2_route.rutas["ANY /{proxy+}"|"POST /v1/auth/login"]`
y `aws_apigatewayv2_stage.default`: 7 recursos; desde INF-2.1, 8 con `aws_cloudwatch_log_metric_filter.localize`.
Detalles que explican un `plan`:
- El formato de los *access logs* se genera con `jsonencode`, que ordena las claves: AWS guarda la misma cadena y el
  `plan` queda vacío. Cambiar un campo es editar §5.10, `modules/borde/main.tf` y `CAMPOS_LOG` de `validate14.py`.
- La integración fija `payload_format_version = "1.0"` (la única que admite `HTTP_PROXY`) y `timeout_milliseconds =
  30000` (el máximo; R7), los valores que devuelve AWS.
- La etapa depende de las rutas (`route_settings` exige que la ruta exista). Con `auto_deploy`, AWS crea los
  despliegues: no hay `aws_apigatewayv2_deployment`.
- Destruir la API exige quitar antes `prevent_destroy` (R8).
- El filtro `localize` vive aquí porque el *log group* y su formato son de `borde`; la alarma que lo lee, en `computo`.
  Patrón `{ ($.httpMethod = "POST") && ($.path = "/v1/localize") }` (valor 1, unidad `Count`): mira `httpMethod` y
  `path` porque `/v1/localize` entra por `ANY /{proxy+}` (`routeKey` no la distingue), con comillas porque todos los
  valores del formato son cadenas (§5.10). Si el backend cambia la ruta de localización, se cambian aquí el patrón y
  `LINEAS_PRUEBA` de `validate21.py`. Una tercera ruta `POST /v1/localize` (con *throttling* propio, R10) se descartó
  en ADR-INF-15. CloudWatch admite alarmas sobre métricas que todavía no existen: no hace falta orden entre el filtro y
  la alarma.

**Módulo `observabilidad` (INF-3.1)**

| Entrada | Tipo | Valor que le pasa `envs/dev` |
|---|---|---|
| `prefijo` | `string` | `local.prefijo` (topic `<prefijo>-alertas`, alarmas `<prefijo>-<clave>`, regla `<prefijo>-tarea-detenida`) |
| `region` | `string` | `var.region` (`aws:SourceArn` de las alarmas en la política del topic) |
| `cuenta_id` | `string` de 12 dígitos | `var.aws_account_id` (condiciones de la política) |
| `correo_alertas` | `string`, validado como dirección de correo | `var.correo_alertas` |
| `api_id` | `string` | `module.borde.api_id` |
| `cluster`, `cluster_arn` | `string` | `module.computo.cluster`, `module.computo.cluster_arn` |
| `servicios` | `map(string)` con `api`, `worker` y `embedding` (si no, falla la validación) | `module.computo.servicios` |
| `colas` | mapa de `{ nombre, url, arn }` con `ingesta_dlq` y `purga_dlq` (si no, falla la validación) | `module.datos.colas` |
| `rds_identificador` | `string` | `module.datos.rds_identificador` |

| Salida | Valor | La usa |
|---|---|---|
| `sns_alertas_arn` | ARN del topic | output `sns_alertas_arn` |

Por dentro: `aws_sns_topic.alertas`, `aws_sns_topic_policy.alertas` (de `data "aws_iam_policy_document" "alertas"`),
`aws_sns_topic_subscription.correo`, `aws_cloudwatch_metric_alarm.alarmas["api-5xx"|"ingesta-dlq"|"purga-dlq"|
"embedding-encendida"|"rds-almacenamiento"|"rds-creditos-cpu"]` (un `for_each` sobre `local.alarmas`, cuyas claves
son el nombre sin el prefijo), `aws_cloudwatch_event_rule.tarea_detenida` y `aws_cloudwatch_event_target.tarea_detenida`:
11 recursos, más el `data`. Detalles que explican un `plan` o un comportamiento:
- Cada entrada de `local.alarmas` es `{ descripcion, espacio, metrica, dimensiones (mapa nombre → valor), estadistica,
  periodo, periodos, comparacion, umbral }`. `periodos` va a `evaluation_periods` y a `datapoints_to_alarm`;
  `treat_missing_data = "notBreaching"` y `alarm_actions = [topic]` son fijos para todas. Añadir una alarma es añadir
  una entrada (su clave es el nombre sin el prefijo) y seguir la regla de §5.10.
- Antes de un `apply` que cree el módulo (o lo recree tras un `destroy`), comprobar que los nombres de §5.1 del topic,
  las alarmas y la regla están libres (`validation-3-1` §5, paso 1): `CreateTopic`, `PutMetricAlarm` y `PutRule` no
  fallan con un nombre que ya existe, lo sobrescriben, y Terraform se quedaría con un recurso ajeno sin avisar.
- El `plan` de INF-3.1 (0.14.0) fueron 11 altas, ninguna modificación ni baja, y el output nuevo (`+ sns_alertas_arn`).
  Los outputs nuevos de `borde`, `computo` y `datos` no cambian ningún recurso. El de 0.15.0 fue `Plan: 0 to add, 1 to
  change, 0 to destroy.`: solo el `event_pattern` de `aws_cloudwatch_event_rule.tarea_detenida` (en `detail`, `group`
  pasa a ser la primera rama de `"$or"`, con la rama `startedBy` al lado); aplicado el 2026-10-26 (ejecución
  40414967226 de `infra.yml`, `0 added, 1 changed, 0 destroyed`).
- La política nombra la regla con su ARN escrito (`arn:aws:events:<region>:<cuenta>:rule/<prefijo>-tarea-detenida`, bus
  `default`), no con `aws_cloudwatch_event_rule.tarea_detenida.arn`: con la referencia, cualquier cambio en sitio de la
  regla aplaza la lectura del `data` al `apply` y el `plan` muestra también `aws_sns_topic_policy.alertas` como
  cambiada (`policy` *known after apply*), aunque quede igual (pasó en el primer `plan` de 0.15.0). El `data` se lee
  en el `plan` porque solo depende del ARN del topic, que no cambia.
- El patrón se escribe con `jsonencode` (ordena las claves: `"$or"` va antes que `clusterArn`); la lista de `group`
  sale de `servicios` en orden fijo (`api`, `embedding`, `worker`) y el `startedBy` de prueba, de
  `local.marca_prueba` (`validacion-3-1`, el `MARCA` de `validate31.py`). Su texto exacto está en §5.10.
- El destino depende de la política (`depends_on`): sin ella, la primera invocación fallaría.
- La suscripción `email` se crea «pendiente de confirmación» (el proveedor la guarda con su ARN y
  `pending_confirmation = true`); confirmarla solo cambia atributos calculados, así que el `plan` siguiente queda vacío
  (comprobado el 2026-10-26: tras el `apply` y la confirmación, `plan -detailed-exitcode` da `No changes` y código 0). El enlace de confirmación vale 2 días (documentación de
  `sns:Subscribe`). Si la suscripción desaparece (baja desde el enlace de un aviso), el `plan` la vuelve a crear.
- Las descripciones de las alarmas y de la regla van sin tildes ni `§` (como las de §5.7) y dicen qué revisar: llegan
  en el correo.
- Las alarmas no se superponen con las de escalado de INF-2.1 (nombres de §5.1 distintos; las de INF-2.1 viven en
  `computo/escalado.tf` y no avisan).

**Proveedores y lock**
- `envs/dev/.terraform.lock.hcl` fija hoy `hashicorp/aws` 6.70.0 y, desde INF-1.2, `hashicorp/random` (3.x) con
  *hashes* de `linux_amd64`, `windows_amd64`, `darwin_amd64` y `darwin_arm64`. CI usa `init -lockfile=readonly`: si el
  lock no tiene un proveedor o su *hash*, el job falla en `terraform init`.
- Añadir un proveedor (como `hashicorp/random` en INF-1.2): `init` **sin** `-upgrade`, que instala solo lo que falta y
  conserva las versiones ya fijadas, y después `providers lock` con las cuatro plataformas:
  ```bash
  cd INFRASTRUCTURA_TERRAFORM/project
  terraform -chdir=envs/dev init -input=false
  terraform -chdir=envs/dev providers lock -platform=linux_amd64 -platform=windows_amd64 \
    -platform=darwin_amd64 -platform=darwin_arm64
  ```
  Actualizar uno es lo mismo con `init -upgrade`, que sube **todos** los proveedores hasta donde permita su
  restricción: va en su propio cambio. En ambos casos el lock se versiona en el mismo commit.

**Lo que hace fallar a CI** (antes de llegar al `plan`)
- `terraform fmt -check -recursive` sobre `project/`: se corre `terraform fmt -recursive` antes de hacer commit.
- TFLint (`project/.tflint.hcl`: preset `recommended` y *ruleset* de AWS 0.50.0) en cada directorio de `project/`,
  `bootstrap/` incluido. Cualquier aviso falla el job: variables sin `type`, variables, `locals` o `data` sin usar
  (salvo con `# tflint-ignore` justificado), módulos sin `required_version`, proveedores sin versión, o valores que el
  *ruleset* de AWS sabe inválidos (tipos de instancia, clases de RDS…). TFLint no está instalado en las máquinas del
  equipo: lo ejecuta solo CI.

**Trabajo en local**: `export AWS_PROFILE=<perfil>` y una vez `terraform -chdir=envs/dev init`. `plan` en local está
permitido (toma el bloqueo unos segundos); `apply` va por `infra.yml` (§3.9).

**Ayudas propias de `validate02.py`** (no están en `comun.py`): procesos de `terraform` en segundo plano que se detienen
con SIGINT para que suelten el bloqueo, y toma del bloqueo creando el `.tflock` con escritura condicional, porque desde
Terraform 1.15 `terraform console` ya no lo toma. Si otro validador las necesita, se mueven a `comun.py` y se añaden a
la tabla de §5.11.

**Ayudas propias de `validate21.py`** (no están en `comun.py`; si otro validador las necesita, se mueven allí y se
añaden a §5.11): `lector(ctx, clave)`, un `comun.LectorCola` (§5.11; hasta INF-3.1 la clase estaba aquí) con
visibilidad de 120 s y el clasificador de abajo, que borra los propios y los restos de otra ejecución con más de 15 min;
`clasificar(cuerpo, sello)` («propio», «resto» o «ajeno») según el `RequestId` `validacion-2-1-…` de
los mensajes con forma de `s3:TestEvent`; `vaciar`, que borra los propios, espera a que SQS cuente 0 y devuelve el
último uso; `actividad_de` y `actividad_esperada`, que buscan en `describe-scaling-activities` la actividad cuya
`Cause` cita una alarma o política por su nombre completo (`worker-cola` es prefijo de otros nombres), aceptando
`Pending`, `InProgress` o `Successful`; y el diccionario `T` con todos los tiempos de espera.

**Ayudas propias de `validate31.py`** (no están en `comun.py`; las mismas reglas): `alarmas_esperadas(api_id)` y
`patron_esperado()` (lo de §5.10, para comparar con AWS); `evento_ecs(group, stop_code, started_by=, cluster=,
last_status=)`, un evento `ECS Task State Change` sintético con los campos que exige `events:TestEventPattern`, y
`CASOS_PATRON`, la lista `(descripción, evento, ¿avisa?)` que C1b prueba contra el patrón guardado en AWS: avisan
`service:worker` y `service:embedding` con `EssentialContainerExited`, `service:api` con `TaskFailedToStart` y la tarea
de prueba (`family:campus-locator-dev-validacion` con `startedBy = validacion-3-1`); no avisan `migrate` aunque salga
con 0, la tarea de validación de otro validador (`startedBy = validacion-1-3`), `ServiceSchedulerInitiated`, otro
clúster ni `lastStatus = DEPROVISIONING`; `clasificar(cuerpo, sello)` de los mensajes de prueba de
las DLQ (`{"validacion": "validacion-3-1-<sello>"}`; «resto» si son de otra ejecución con más de 1 h) y `lector(ctx,
clave)`, su `comun.LectorCola`; `suscripcion(ctx)`, que exige una suscripción `email` a `correo_alertas` confirmada
(`ListSubscriptionsByTopic` + `GetSubscriptionAttributes`) y devuelve su descripción con el correo enmascarado
(`enmascarar`: «fr…@gmail.com»; ningún validador imprime el correo entero); `puntos`, `suma` y `maximos`, valores por
minuto de una métrica con `GetMetricStatistics` desde el minuto de un momento; `esperar_entregas(ctx, desde, que)`,
que espera ≥ 1 `NumberOfNotificationsDelivered` del topic y falla con la causa probable (sin publicaciones, o
publicadas sin entregar: suscripción sin confirmar); `metrica_regla`, que lee las métricas de `AWS/Events` de la regla
con la dimensión `RuleName` (como las publica hoy la cuenta para el bus por defecto) y también con `EventBusName` +
`RuleName`, y toma la mayor; `paso_a_alarm` y `accion_publicada`, que leen la historia de una alarma (`StateUpdate`
«… to ALARM» y `Action`; una acción con «fail» en el resumen es un fallo de publicación) desde un momento menos
`TOLERANCIA_RELOJ` (60 s, por si el reloj local va adelantado respecto al de AWS); `elegir_dlq`, que toma la primera
DLQ (`ingesta`, luego `purga`) sin mensajes visibles, en vuelo ni retrasados y con su alarma fuera de `ALARM`, espera
hasta `T["ok"]` a que una vacía en `ALARM` vuelva a `OK` y, si las dos tienen mensajes, falla sin enviar nada;
`limpiar_restos` (al empezar: en cada DLQ con entre 1 y 10 visibles y ninguno en vuelo, una lectura con `lector`),
`borrar_propios` (borra los mensajes propios que quedan, contados en `Contexto.pendientes`; falla si no los encuentra)
y `detener_tareas` (`StopTask` de las tareas `RUNNING` con `startedBy = validacion-3-1`); `lanzar_tarea`, que lanza una
sola vez la tarea de prueba (sin `group`, con `startedBy = MARCA`; C3a y C3b la comparten) y guarda el error si falla;
y el diccionario `T` con los tiempos
(`ok` 10 min, `alarma` 20, `accion` 2, `sns` 10, `tarea` 10, `eventos` 10, `leer` 60 s, `sondeo` 30 s).
Trampa: `leer_correo` saca `correo_alertas` de `envs/dev/terraform.tfvars` con la expresión
`^correo_alertas\s*=\s*"([^"]+)"`: la asignación tiene que estar al principio de una línea y con comillas dobles (como
hoy); con otro formato, C1c, C2a y C3b fallan con «no tiene correo_alertas». Lo mismo vale para `apagado_embedding` y
`leer_tfvars` de `validate21.py`.

`validate11.py` tiene su propia `terraform_plan()`: lanza `terraform` en otra sesión de procesos (otro grupo en
Windows) con la salida en archivos temporales y, con Ctrl+C, le reenvía la interrupción (SIGINT; CTRL_BREAK en Windows)
y espera hasta 120 s a que suelte el bloqueo, ignorando mientras más Ctrl+C, SIGTERM y SIGHUP. `comun.ejecutar` lo
mataría al instante; y con tuberías, si Python muriera, terraform recibiría SIGPIPE antes de soltar el bloqueo. Usa
`comun._entorno_proceso()` para tener el mismo entorno que `ejecutar`. Con esta ya hay dos variantes de la misma idea:
el próximo validador que lance un `plan` las une en `comun.py` (y actualiza §5.11).

### 5.13 Borde: lo que ve el cliente y lo que recibe `api`

Contrato del borde (§3.3) para `FRONTEND_KOTLIN` (respuestas que no vienen del backend) y `BACKEND_FASTAPI` (qué le
llega a `api`). Comprobado el 2026-10-24 a las 20:13 (Bogotá) contra `api_base_url` (§5.2), con `api` en 0 réplicas,
con `curl` y con los *access logs* de `/campus-locator/dev/apigw`. Lo que no se ha comprobado lo dice cada fila.

**Respuestas que genera API Gateway.** No pasan por `api`: no hay log del backend, y el *access log* las registra con
`integrationStatus = "-"`. Su cuerpo es `{"message": "..."}`, no el formato de error de
`BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5; el cliente las distingue por eso.

| Situación | Código y cuerpo | Comprobado |
|---|---|---|
| `api` sin instancias en Cloud Map (0 réplicas, o ninguna tarea registrada todavía) | `500` `{"message":"Internal Server Error"}` (no 503) | Sí: `GET /v1/health`, `POST /v1/auth/login` y un `POST /v1/localize` de 9 MB con `api` en 0. Con `content-type: application/json` y cabecera `apigw-requestid` |
| *Throttling* (§5.10; aproximado, §3.3) | `429` `{"message":"Too Many Requests"}` | Sí: 38 de 100 `POST /v1/auth/login` lanzados con 50 en paralelo |
| Cuerpo de más de 10 MB | `413` `{"message":"Request Entity Too Large"}` | Sí: 11 000 000 bytes dan 413; 9 000 000 pasan (y dieron 500 por no haber `api`) |
| `api` tarda más de 30 s (tiempo máximo de la integración, R7) | Sin comprobar | No: la imagen de prueba responde al instante. Se comprueba con un endpoint lento del backend |
| Ruta que no casa con ninguna de las dos | No ocurre: `ANY /{proxy+}` también recoge `/` | Sí: `GET /` dio el 500 de la primera fila y su *access log* dice `routeKey = ANY /{proxy+}`. No hay 404 de API Gateway; un 404 lo da el backend (o la imagen de prueba) |

Que la cabecera `apigw-requestid` y el `content-type: application/json` estén también en los 429 y 413 no se comprobó.
El `apigw-requestid` de cualquier respuesta es el `requestId` del *access log* (§5.10): sirve para buscar una petición.

**Lo que recibe `api`** (integración `HTTP_PROXY`, `payload_format_version = 1.0`, §5.12):

| Aspecto | Contrato | Comprobado |
|---|---|---|
| Ruta | Tal cual llega a API Gateway (`/v1/...`), sin prefijo de etapa: la etapa es `$default` | Sí: con la imagen de prueba, que solo responde 200 a `/v1/health` exacto, `GET {api_base_url}/v1/health` da 200 (INF-1.4 C1b) |
| Método y cuerpo | Se reenvían tal cual | El método sí: los `POST` de INF-1.4 C2b llegaron a `api` (501 de la imagen de prueba). El cuerpo, no |
| Cadena de consulta y cabeceras del cliente | Se reenvían | No comprobado |
| Cabeceras que añade API Gateway (IP del cliente, protocolo) | No hay contrato todavía | **A verificar con la imagen de BE-1.1**. Hasta entonces el backend no puede fiarse de ninguna cabecera para identificar al cliente (R10) |
| Transporte | El TLS termina en API Gateway; del VPC Link a `api` es HTTP en claro dentro de la VPC, al puerto 8000 (§5.7) | — |
| Límites | 30 s por petición y 10 MB de cuerpo (§3.3) | 10 MB sí (arriba); 30 s no |

---

## 6. Decisiones de diseño (ADR)

Formato: contexto → decisión → consecuencias. Estado entre paréntesis.

**ADR-INF-01 — Solo AWS, una cuenta, `us-east-1`, entorno `dev` (aceptada).**
El equipo descartó GCP. `us-east-1` es la región más barata con todos los servicios necesarios; la latencia desde
Medellín es aceptable para peticiones de varios segundos. *Consecuencia:* no hay capa de abstracción multinube.

**ADR-INF-02 — Sin NAT Gateway: tareas en subredes públicas con IP pública (aceptada).**
Un NAT Gateway cuesta ~33 USD/mes y cinco *interface endpoints* (ECR ×2, Logs, SQS, Secrets Manager) ~37 USD/mes en
una zona; ambos se comen un tercio del presupuesto. Una IP pública por tarea cuesta 3,65 USD/mes. *Consecuencia:* las
tareas tienen dirección pública; la protección recae en grupos de seguridad sin reglas entrantes desde internet
(riesgo R2). En `prod` se reevalúa.

**ADR-INF-03 — Una sola zona para cómputo y base de datos (aceptada).**
Multi-AZ duplica RDS y no aporta en desarrollo. Las subredes de `us-east-1b` existen solo porque el grupo de subredes
de RDS exige dos zonas. *Consecuencia:* una caída de `us-east-1a` deja el sistema fuera de servicio (riesgo R3).

**ADR-INF-04 — API Gateway HTTP API + VPC Link + Cloud Map en lugar de un ALB (aceptada).**
Un ALB cuesta ~16 USD/mes más dos IPv4 y no da HTTPS sin dominio propio y certificado de ACM; Android bloquea HTTP en
claro. La HTTP API da HTTPS gestionado, *throttling* y cobro por petición. *Consecuencias:* límites de 30 s y 10 MB
(riesgo R7); el servicio `api` debe registrarse con SRV; la URL cambia si se destruye la API (riesgo R8).

**ADR-INF-05 — ECS Fargate para los tres procesos (aceptada).**
Lambda no encaja con un modelo de PyTorch de cientos de MB (arranque en frío de varios segundos por petición) ni con
un consumidor de colas que llama a ese modelo. EC2 exige administrar máquinas. Fargate permite apagar por horario y
escalar a 0 el `worker`. *En 0.7.0 y 0.8.0* se planeó `embedding` sobre EC2 con GPU
(ADR-INF-13); desde 0.9.0 los tres procesos vuelven a Fargate (ADR-INF-14).

**ADR-INF-06 — Embeddings en CPU y arquitectura x86_64 (reemplazada por ADR-INF-13 en 0.7.0 y por ADR-INF-14 en 0.9.0).**
Una GPU (`g4dn.xlarge`) supera el presupuesto por sí sola. ViT-B/14 en 1 vCPU da latencias de segundos para 5 fotos,
aceptable para `/v1/localize` (se mide en EMB-3.1). Graviton (ARM64) ahorraría ~20 % de Fargate, pero exige
construir imágenes multiplataforma y validar las ruedas de PyTorch; se deja como optimización (PLAN, INF-6.1).

**ADR-INF-07 — RDS PostgreSQL 17 + pgvector, contraseña generada por Terraform sin rotación (aceptada).**
pgvector evita un segundo almacén para vectores. La contraseña gestionada por RDS rota cada 7 días y las tareas la
leen solo al arrancar, lo que rompería las conexiones tras la rotación. *Consecuencia:* la contraseña vive en el
estado de Terraform (riesgo R5); rotación manual con `terraform apply -replace`.

**ADR-INF-08 — Estado remoto en S3 con bloqueo nativo, sin DynamoDB (aceptada).**
Terraform ≥ 1.10 bloquea con un archivo `.tflock` en el mismo bucket. Menos piezas y sin costo adicional.

**ADR-INF-09 — Terraform crea los servicios; CI despliega las imágenes (aceptada).**
Si Terraform gestionara la etiqueta de imagen, cada despliegue de código exigiría un `apply`. Los servicios ignoran
`task_definition` y `desired_count`; CI registra revisiones nuevas. *Consecuencia:* cambiar CPU, memoria o variables de
una tarea en Terraform crea una revisión con la imagen inicial: el workflow del servicio debe ejecutarse después
(se documenta en el PR).

**ADR-INF-10 — Ingesta por eventos S3 → SQS, sin SNS intermedio (aceptada).**
Un solo consumidor; SNS solo añadiría un salto. La DLQ conserva los fallos 14 días para re-procesarlos.

**ADR-INF-11 — Horario de encendido en `dev` y presupuesto con avisos (aceptada; modificada por ADR-INF-13 y ADR-INF-14).**
`embedding` es el mayor costo variable. Apagarlo de noche ahorra ~13 USD/mes. *Consecuencia:* `/v1/localize` no
funciona fuera de horario; la app debe mostrar el error del backend (`FRONTEND_KOTLIN`, PLAN). *Desde 0.7.0*,
`embedding` no tiene horario de encendido: está apagado por defecto y se enciende a mano; del horario queda el apagado
de las 22:00 como red de seguridad.

**ADR-INF-12 — *Permissions boundary* obligatorio en los roles que crea `gha-terraform` (aceptada).**
`gha-terraform` necesita crear roles (ECS), y con `PowerUserAccess` más IAM sobre `campus-locator-*` podía crear un
rol propio con `"Action": "*"` y asumirlo: las denegaciones solas no bastaban. Todo rol nuevo exige el boundary
`campus-locator-limite-roles` (sin IAM ni `sts:AssumeRole`, sin salir de la región ni tocar el bucket de estado), que
no se puede quitar ni editar, y `gha-terraform` no puede asumir roles. *Consecuencias:* los roles de `envs/dev`
declaran `permissions_boundary` (output `limite_roles_arn`) y uno sin él falla con `AccessDenied` en
`iam:CreateRole`; los roles `campus-locator-*` ajenos a este diseño quedan fuera del modelo y deben borrarse (R11).

**ADR-INF-13 — `embedding` en GPU (EC2 `g4dn.xlarge`), apagado por defecto (descartada en 0.9.0 antes de aplicarse: la cuenta tiene cupo 0 de instancias G; la reemplaza ADR-INF-14).**
El equipo pide que `POST /v1/localize` responda en menos de 1 s. Medición de referencia (ViT-B/14 en fp32, un núcleo
de un Xeon de 2,1 GHz): ~1,1 s por foto a 224 px y ~9,3 s a 518 px, así que 5 fotos en 1 vCPU tardan ~5,5 s o ~47 s
(más que los 30 s de API Gateway); una T4 las procesa en decenas de milisegundos. En `dev` prueban 1–3 personas a
ratos: una GPU con horario fijo pasaría casi todo el tiempo ociosa (~255 USD/mes con 16 h/día). *Decisión:*
`embedding` corre en ECS sobre EC2, con un proveedor de capacidad sobre un grupo de autoescalado de 0 a 1
`g4dn.xlarge` bajo demanda (Spot ahorra poco con tan pocas horas y añade cortes); apagado por defecto, se enciende a
mano y se apaga solo tras 45 min sin uso y a las 22:00 (§3.4). *Consecuencias:* se paga solo lo encendido (~0,53
USD/h; §3.10); la primera petición tras encender espera el arranque (5–10 min, R6) y mientras tanto `/v1/localize` da
`503 EMBEDDING_NO_DISPONIBLE`; la ingesta solo avanza con la GPU encendida; hace falta cupo de instancias G (R9); la
imagen de embeddings lleva CUDA y los pesos dentro; un despliegue de `embedding` lo detiene unos minutos (una sola
GPU); Graviton deja de aplicar a `embedding`. La latencia real se mide en EMB-3.1. *Desde 0.8.0*, el grupo admite una
segunda instancia, solo para tareas sueltas con GPU (validadores y medición de embeddings) mientras el servicio está
encendido; eso pide un cupo de 8 vCPU (R9).

**ADR-INF-14 — `embedding` en Fargate (2 vCPU) con DINOv2 ViT-S/14, apagado por defecto (aceptada; reemplaza a ADR-INF-13
y ADR-INF-06).**
La cuenta tiene cupo 0 de instancias G y el aumento puede tardar días, más de lo que el equipo puede esperar.
*Decisión:* `embedding` vuelve a Fargate (`X86_64`) con 2 vCPU / 4 GB y el modelo pasa a DINOv2 ViT-S/14 (22 M
parámetros, vectores de 384; `SERVICE_EMBEDDING` ADR-EMB-11), que hace unas 4 veces menos cómputo por foto que
ViT-B/14. Se mantiene el encendido de ADR-INF-13: apagado por defecto, a mano con `src/ops/embedding.py encender` y
apagado solo tras 45 min sin uso y a las 22:00 (§3.4). Estimación sin medir: 5 fotos en 0,5–1,5 s con 2 vCPU, a partir
de la medición de referencia de ADR-INF-13 y la proporción de cómputo. *Consecuencias:* ~0,10 USD por hora encendida
(§3.10); arranque de 2–3 min (R6); sin cupos especiales ni instancias que administrar; el objetivo de p95 ≤ 1 s en el
servidor no está garantizado: se mide en EMB-3.1 y BE-3.2 y, si no se cumple, las palancas son ONNX Runtime (mejor
antes de indexar el dataset real, porque cambia los vectores) o 4 vCPU (embeddings §4.4); Graviton sigue como
optimización (INF-6.1).

**ADR-INF-15 — Apagado de `embedding` y escalado de `worker` con alarmas de CloudWatch y Application Auto Scaling
(aceptada; INF-2.1).**
ADR-INF-14 pide apagar `embedding` tras 45 min sin uso y subir `worker` solo con `embedding` encendido, sin pagar
*Container Insights* (§3.8) ni operar código propio. *Decisión:* todo con alarmas de expresión (*metric math*) que
disparan políticas por pasos de capacidad exacta sobre los objetivos de Application Auto Scaling de los dos servicios:
- El uso de `/v1/localize` sale de un filtro de métricas sobre los *access logs* (`borde`), que mira `httpMethod` y
  `path`. Se descartó añadir una ruta `POST /v1/localize`: daría un `routeKey` propio y *throttling* propio (R10), pero
  cambia el borde y el contrato de §5.10 con la app y el backend; queda como opción para INF-6.1.
- «`embedding` encendido» se mide con la métrica gratuita `CPUUtilization` del servicio, que ECS solo publica con
  tareas en marcha, y se exige en el mismo minuto que los mensajes, dentro de la alarma de subida de `worker`. El rango
  máximo de `worker` (0 con `embedding.py apagar` y a las 22:00) no basta: el apagado por inactividad no puede
  cambiarlo.
- La alarma de inactividad puede quedar en `ALARM` mientras `embedding` está apagado y, en ese estado, Application
  Auto Scaling repite su acción cada minuto. Por eso encender es «publicar `EmbeddingEncendidos`, esperar a que la
  alarma lo vea, poner 1» (contrato de §5.10), no solo `desiredCount = 1`; a cambio, un `embedding` encendido a mano
  sin ese paso se apaga solo enseguida, lo que también protege del gasto (R13).
- Una política de capacidad exacta por sentido, con dos pasos que cubren todos los valores con la misma capacidad:
  el resultado no depende de qué muestras agregue Application Auto Scaling, y la alarma ya decidió cuándo actuar.
Se descartaron una Lambda programada (más código, permisos y otro rol con el *boundary*) y *Container Insights*
(`RunningTaskCount`, con costo). *Consecuencias:* sin código en ejecución propio; ~1,6 USD/mes por las 16 métricas
de las alarmas y 0,6 por las dos métricas propias (§3.10); los tiempos dependen del retraso con que SQS y ECS publican
(§3.4): la subida de `worker` puede tardar de 2 a 15 min y el apagado llega a los 45 min ± 2.

**ADR-INF-16 — Alertas por correo con un topic SNS sin cifrar; la regla manda el evento tal cual (aceptada; INF-3.1).**
HU-22 pide enterarse de los fallos sin mirar la consola, con 1–3 personas y sin presupuesto para herramientas.
*Decisión:* un solo topic con una suscripción por correo; las alarmas de §5.10 avisan solo al pasar a `ALARM` (un correo
por incidente; volver a `OK` no avisa) y tratan la falta de datos como «no incumple»; la regla de EventBridge publica
el evento completo, sin transformador de entrada (nada que mantener ni dato que se pierda; a cambio, el correo es un
JSON); el topic no se cifra (con `aws/sns`, CloudWatch y EventBridge no pueden publicar; una clave de KMS propia cuesta
1 USD/mes y los avisos no llevan datos sensibles), y su política repite la declaración por defecto de AWS y añade a
CloudWatch y a la regla. Se descartaron Chatbot/Slack (otra integración que mantener) y avisos al volver a `OK` (el
doble de correos). Para validar la regla sin detener `api`, `worker` ni `embedding`, `validate31.py` lanza la tarea de
validación con `group = service:worker` (`worker` suele estar en 0; con `service:api` o `service:embedding`, una tarea
falsa podría confundirse con las reales en `ListTasks` o en las métricas de la alarma de subida de `worker`, sin
comprobar). *Consecuencias:* 0,6 USD/mes (§3.10); hay que confirmar la suscripción tras el primer `apply` (y tras
cualquier cambio de `correo_alertas`); cualquiera que reciba un aviso puede darse de baja desde el correo (R14).
*Corrección en 0.15.0:* esa forma de validar la regla no funciona: ECS no admite `group = service:…` en una tarea
suelta («Invalid namespace for group.», §3.8). Decisión del maestro del 2026-10-26 (opción A de las tres de CHANGELOG
0.15.0): la regla gana una segunda rama, `startedBy = validacion-3-1`, que solo lleva la tarea de prueba de
`validate31.py` (lanzada sin `group`), y la rama de los servicios se prueba con `events:TestEventPattern`. Se
descartaron un `group` propio sin espacio de nombres (que ECS lo acepte estaba sin comprobar) y probar solo el patrón
sin un evento real (no cumpliría «llega el correo» de PLAN C3). *Consecuencia:* la regla avisa también de cualquier
tarea con ese `startedBy` que se detenga por error: ningún otro validador ni proceso debe usarlo. El resto de esta
decisión sigue igual.

---

## 7. Riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | El gasto supera 100 USD/mes | Media | Alto | Presupuesto con avisos, `embedding` apagado por defecto y con apagado automático (ADR-INF-14), tamaños mínimos, conservar 5 imágenes en ECR, revisar *Cost Explorer* al cerrar cada lote. La cuenta y el presupuesto se comparten con otro proyecto del equipo (trend-analyzer, recursos `ta-*`) |
| R2 | Tareas con IP pública expuestas | Baja | Alto | Grupos de seguridad sin entrada desde internet; `embedding` sin permisos de AWS; imágenes base mínimas con escaneo de ECR; grupo `default` sin reglas; `validate11.py` C4 comprueba que ninguna regla entrante de la VPC admite `0.0.0.0/0` ni `::/0` |
| R3 | Caída de `us-east-1a` | Baja | Alto | Aceptado en `dev`; Multi-AZ en `prod` (Fase 6) |
| R4 | `db.t4g.micro` (1 GiB) se queda corto: índice HNSW en memoria, conexiones, créditos de CPU | Media | Medio | Alarma de créditos; el índice cabe holgado hasta ~50 000 vectores de 768 dimensiones; subir a `db.t4g.small` (~23 USD/mes) si hace falta |
| R5 | Contraseña de la base y demás secretos en el estado de Terraform | Media | Medio | Bucket de estado privado, cifrado, versionado y solo TLS. Lo leen el administrador, `gha-terraform` y `gha-terraform-plan`; este último desde cualquier PR del repositorio, que solo abre quien tiene escritura. Aceptado en `dev`; se revisa en INF-6.1 |
| R6 | Imagen de embeddings de ~1,8 GB: 3–6 min desde `embedding.py encender` hasta `embedding` sano (1–3 de espera a la alarma de inactividad, §5.10) | Alta | Bajo | Encender antes de probar (`embedding.py estado` dice cuándo está listo); *start period* de 180 s; `worker` solo sube con `embedding` encendido |
| R7 | Límite de 30 s y 10 MB de API Gateway | Media | Medio | Fotos del dataset directo a S3; `/v1/localize` limitado a 5 fotos de ≤ 1,5 MB (contrato del backend) |
| R8 | La URL de la API cambia si se recrea la HTTP API, y `ApiConfig.kt` queda desactualizado | Baja | Medio | `prevent_destroy` en la API; dominio propio en Fase 6 |
| R9 | Cuotas por defecto de una cuenta nueva (vCPU de Fargate, etc.) | Baja | Medio | El sistema usa ~2,5 vCPU con todo encendido; solicitar aumento si un `apply` falla por cuota. Sin GPU desde 0.9.0: el cupo de instancias G de la cuenta es 0 (ADR-INF-14) |
| R10 | `/v1/localize` es público: abuso que dispara costos; `/v1/auth/login` admite fuerza bruta | Baja | Medio | *Throttling* (aproximado: frena volumen, no intentos sueltos, §3.3); alarma de 5xx; en `prod`, WAF o clave de app. Límite de intentos de inicio de sesión: lo tiene que poner el backend (`BACKEND_FASTAPI`; propuesta en CHANGELOG 0.12.0). Si limita por IP, la cabecera con la IP del cliente está sin verificar (§5.13) |
| R11 | Recursos de un intento anterior (oct-2026) siguen en la cuenta: cuestan y pueden chocar con nombres de §5.1 (sobre todo el *namespace* de Cloud Map `campus-locator.local`, con INF-1.3) | Alta | Medio | Revisado el 2026-10-24: no había otra VPC `campus-locator-dev-vpc` (C2a de INF-1.1) ni nada que choque con INF-1.2 (el bucket del dataset ya no existe; sin instancias, *snapshots*, grupos de parámetros ni de subredes de RDS; sin colas; `campus-locator-dev/jwt-secret` está en borrado programado y su nombre no choca). Antes de INF-1.3, inventariar y limpiar el resto: clúster y servicios de ECS, ECR `campus-locator-dev/*`, *namespace* de Cloud Map, *target group*, *log groups* `/ecs/…`, roles `campus-locator-dev-backend-*` y `-embedding-*` y los buckets `campus-locator-dev-scans-648617469176` y `4uproject-eafit-tfstate` (CHANGELOG 0.3.0). Revisado de nuevo antes de INF-1.3 (`.validacion/inventario-r11b.txt`): ya no quedan roles `campus-locator-dev-*` ni buckets del intento anterior; antes del `apply` de INF-1.3 se confirma que no hay *namespace* `campus-locator.local`, clúster `campus-locator-dev` ni repositorios `campus-locator/*` (`servicediscovery list-namespaces`, `ecs describe-clusters`, `ecr describe-repositories`) |
| R12 | El repositorio es público: los logs de Actions y los comentarios del `plan` los puede leer cualquiera | Alta | Bajo | Terraform oculta los valores `sensitive` (contraseñas, secretos) en el `plan` y en los logs; ningún paso imprime el estado ni credenciales; todo output con un dato sensible se declara `sensitive`; los PR desde *forks* no ejecutan el `plan`. Lo que queda visible (IDs, ARN, URL) no da acceso por sí solo |
| R13 | El apagado automático de `embedding` falla y queda encendido (~2,5 USD/día) | Baja | Medio | Apagado por inactividad y a las 22:00, alarma `campus-locator-dev-embedding-encendida` (> 10 h seguidas; INF-3.1, aplicada el 2026-10-26; su configuración la comprueba `validate31.py` C1a, pero que dispare tras 10 h no se ha observado) y presupuesto con avisos. El apagado por inactividad y el escalado están configurados y revisados (`validate21.py` C2a y C3a), pero observarlos en `dev` es opcional desde 0.13.1: la alarma de INF-3.1 avisa si falla |
| R14 | Los avisos no llegan: suscripción sin confirmar, alguien se da de baja desde el enlace de un correo, o el correo cae en spam | Media | Medio | `validate31.py` C1c comprueba la suscripción confirmada y C2/C3 que SNS entrega; una suscripción borrada la vuelve a crear el siguiente `plan`/`apply` (hay que confirmarla otra vez); la primera vez, marcar el remitente `no-reply@sns.amazonaws.com` como «no es spam». Si el correo deja de servir, se cambia `correo_alertas` en los dos `terraform.tfvars` (§5.3) |

---

## 8. Referencias cruzadas

- Contratos del backend (API, base de datos, mensajes, comandos): `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.
- Contratos del servicio de embeddings: `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5.
- App y puentes WebView: `FRONTEND_KOTLIN/docs/ARCHITECTURE.md` §5.
- Historias de usuario (catálogo único): `FRONTEND_KOTLIN/docs/PLAN.md` §5.
