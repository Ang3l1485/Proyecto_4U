# ARCHITECTURE — Infraestructura (`INFRASTRUCTURA_TERRAFORM`)

| Campo | Valor |
|---|---|
| Versión del documento | **0.5.0** (historia en [`CHANGELOG.md`](./CHANGELOG.md)) |
| Fecha | 2026-10-24 |
| Estado | Diseño propuesto. **INF-0.1 e INF-0.2 aplicados** (bootstrap de la cuenta; esqueleto de `envs/dev` y CI de Terraform `infra.yml`); **INF-1.1 (red) escrito, pendiente de aplicar y validar**; el resto, sin código todavía |
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
                                              │   └─ embedding DINOv2 ViT-B/14 (CPU)◄┘  (A record,        │
                                              │                                        Cloud Map)         │
                                              │        │                                                  │
                                              │        ▼  :5432 (subred privada)                          │
                                              │   RDS PostgreSQL 17 + pgvector   campus-locator-dev-db    │
                                              └───────────────────────────────────────────────────────────┘
 Transversal: Secrets Manager · CloudWatch Logs/Alarms → SNS campus-locator-dev-alertas · AWS Budgets · ECR
 Fuera de AWS: GitHub Actions (OIDC) despliega · la app pide teselas a OpenStreetMap
```

### 2.1 Flujos principales

| Flujo | Recorrido | Síncrono |
|---|---|---|
| **Ubicarse** (`POST /v1/localize`) | App → API Gateway → `api` → `embedding` (5 vectores) → RDS (búsqueda kNN) → `api` responde | Sí (objetivo p95 ≤ 5 s) |
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
- Límites que heredan los servicios: **30 s** de tiempo máximo de integración y **10 MB** de carga útil por petición.
  Por eso las fotos del dataset no pasan por la API (van directo a S3 con URL prefirmada).
- La autenticación **no** se valida en API Gateway: el JWT es propio (HS256) y lo verifica FastAPI
  (`BACKEND_FASTAPI/docs/ARCHITECTURE.md`, ADR-BE-03).
- *Access logs* de la API a CloudWatch.

### 3.4 Cómputo: ECS sobre Fargate

Un clúster `campus-locator-dev` con tres servicios y una tarea suelta. Todas las tareas son `X86_64` / Linux
(ADR-INF-06) y usan `awsvpc`.

| Servicio / tarea | Imagen | Proceso | Tamaño | Réplicas | Descubrimiento |
|---|---|---|---|---|---|
| `api` | `campus-locator/backend` | servidor HTTP (FastAPI) en `:8000` | 0,25 vCPU / 0,5 GB | 1 fija | Cloud Map SRV `api.campus-locator.local` |
| `worker` | `campus-locator/backend` (otro comando) | consumidor de `ingesta` y `purga` | 0,25 vCPU / 0,5 GB | 0–1 según la cola, solo en horario | ninguno |
| `embedding` | `campus-locator/embedding` | DINOv2 en CPU en `:8080` | 1 vCPU / 3 GB | 1 en horario, 0 fuera | Cloud Map A `embedding.campus-locator.local` |
| `migrate` (tarea suelta) | `campus-locator/backend` (otro comando) | migraciones Alembic + admin inicial | 0,25 vCPU / 0,5 GB | la lanza CI con `run-task` | ninguno |
| `validacion` (tarea suelta) | pública `postgres:17-alpine` | `psql` y `nslookup` para los validadores (§5.11) | 0,25 vCPU / 0,5 GB | la lanzan los validadores con `run-task` | ninguno |

- Los comandos exactos de cada proceso los define `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.9 y
  `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5.5; esta carpeta solo los referencia en la definición de tarea.
- **Horario de `dev`** (ADR-INF-11): acciones programadas de Application Auto Scaling encienden `embedding` y
  habilitan `worker` de 06:00 a 22:00 (hora de Bogotá). Fuera de horario, `api` sigue respondiendo (`/v1/health`,
  login, lugares, alertas) pero `/v1/localize` devuelve `503 EMBEDDING_NO_DISPONIBLE`.
- **`worker` escala por cola**: alarma `ApproximateNumberOfMessagesVisible ≥ 1` en `ingesta` o `purga` → 1 réplica;
  15 minutos sin mensajes visibles ni en vuelo → 0. Dentro del horario el máximo es 1; fuera, 0.
- *Health checks* de contenedor (§5.7) y *deployment circuit breaker* con *rollback* activado en los tres servicios.
- **ECS Exec** (`enable_execute_command`) solo en `api`, para depurar en `dev` (y para la comprobación de disco de
  BE-3.2). Quien lo use necesita el *Session Manager plugin* de la CLI de AWS. `worker` y `embedding` no lo tienen.
- **Terraform crea los servicios, CI cambia la imagen**: los servicios ignoran cambios en `task_definition` y
  `desired_count` (ADR-INF-09). El contrato de CI está en §5.9.

### 3.5 Datos

**RDS PostgreSQL** (`campus-locator-dev-db`)
- PostgreSQL **17** (≥ 17.1, la que trae pgvector 0.8.0 en RDS), `db.t4g.micro` (2 vCPU, 1 GiB), una sola zona
  (`us-east-1a`), 20 GB `gp3` con autoescalado de almacenamiento hasta 50 GB.
- Sin acceso público; solo admite `:5432` desde los grupos de seguridad de `api`, `worker` y `migrate`.
- Copias automáticas 7 días; *snapshot* final al destruir; `deletion_protection` activado.
- La extensión `vector` la crea la primera migración del backend (`CREATE EXTENSION IF NOT EXISTS vector`).
  Terraform no crea tablas.
- Grupo de parámetros propio (§5.10) con `rds.force_ssl = 1`.

**S3** (`campus-locator-dev-dataset-648617469176`)
- Privado, cifrado SSE-S3, *Block Public Access*, propiedad de objetos `BucketOwnerEnforced`, sin versionado.
- Prefijos y notificación hacia SQS en §5.5. Las fotos de `/v1/localize` **nunca** se escriben aquí: se procesan en
  memoria y se descartan (`BACKEND_FASTAPI/docs/ARCHITECTURE.md`, ADR-BE-06).

**SQS**
- `ingesta`: recibe directamente las notificaciones `ObjectCreated` de S3. DLQ tras 5 recepciones.
- `purga`: la llena la `api` al borrar un video. DLQ tras 5 recepciones.
- Atributos en §5.6. El formato de los mensajes lo define el backend (§5.8 de su documento).

### 3.6 Secretos y configuración

- Tres secretos en Secrets Manager (§5.4). ECS los inyecta como variables de entorno al arrancar cada tarea.
- La contraseña de la base la genera Terraform (`random_password`) y la guarda en el secreto `db`; no hay rotación
  automática en `dev` (ADR-INF-07). Consecuencia: el valor queda en el estado de Terraform, que está cifrado y es
  privado (§3.9).
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

- Un *log group* por proceso, retención 14 días (§5.10).
- Alarmas de CloudWatch publicadas en el topic SNS `campus-locator-dev-alertas` (suscripción por correo, variable
  `correo_alertas`; SNS envía un correo de confirmación y no entrega nada hasta que se confirma): errores 5xx de la API,
  mensajes en cualquier DLQ, CPU de `embedding` sostenida,
  almacenamiento libre y créditos de CPU de RDS (umbrales en §5.10).
- Una regla de **EventBridge** sobre los eventos `ECS Task State Change` avisa al mismo topic cuando una tarea de los
  **servicios** `api`, `worker` o `embedding` se detiene por error: `lastStatus = STOPPED`, `stopCode` =
  `EssentialContainerExited` o `TaskFailedToStart`, y `group` = `service:api`, `service:worker` o
  `service:embedding`. Las tareas sueltas (`migrate`, `validacion` y las que lanzan los validadores con la definición
  de `embedding`) tienen otro `group` y no avisan; su resultado lo lee quien las lanzó. Apagar los servicios por el
  horario da `stopCode = ServiceSchedulerInitiated` y tampoco avisa.
  No se activa *Container Insights* (tiene costo y no hace falta para estas alertas).
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
  pendientes, GitHub deja solo el más reciente, que aplica el árbol completo de `main`). En `main`, el job
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
RDS `db.t4g.micro` 0,016 USD/h; mes de 730 h. Ninguna cifra cuenta con capa gratuita.

| Concepto | Supuesto | USD/mes con horario (16 h/día) | USD/mes 24/7 |
|---|---|---|---|
| `api` (0,25 vCPU / 0,5 GB) | siempre encendida | 9,0 | 9,0 |
| `embedding` (1 vCPU / 3 GB) | 480 h vs 730 h | 25,8 | 39,3 |
| `worker` (0,25 vCPU / 0,5 GB) | ~60 h al mes por cola | 0,7 | 0,7 |
| IPv4 públicas de las tareas | 1 por tarea en marcha | 6,3 | 7,6 |
| RDS `db.t4g.micro` + 20 GB `gp3` | una zona | 14,0 | 14,0 |
| Secrets Manager | 3 secretos | 1,2 | 1,2 |
| CloudWatch (logs ~2 GB, ~8 alarmas) | | 2,0 | 2,0 |
| ECR (~10 GB entre versiones) | conservar 5 por repo | 1,0 | 1,0 |
| Cloud Map, API Gateway, S3, SQS, transferencia | tráfico de desarrollo | ~3,0 | ~3,0 |
| **Total aproximado** | | **≈ 63** | **≈ 78** |

Cargos que pueden aparecer y no están en la tabla: créditos de CPU de RDS (los `t4g` corren en modo *unlimited* y
cobran si la media de 24 h supera la línea base), almacenamiento de copias por encima del tamaño de la base, y
cualquier recurso creado a mano fuera de Terraform. El presupuesto (§3.8) avisa antes de pasar de 100 USD.

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
    │   ├── computo/             ECR, clúster, Cloud Map, roles, definiciones de tarea (incluida la de validación), servicios, autoescalado
    │   ├── borde/               HTTP API, VPC Link, integración con Cloud Map, rutas, throttling, access logs
    │   └── observabilidad/      log groups, topic SNS, alarmas, regla de EventBridge
    ├── pruebas/
    │   └── imagen-prueba/       Dockerfile y servidor mínimo de la imagen `bootstrap` (§5.11)
    ├── src/
    │   └── ops/                 validate<fase><n>.py y comun.py: validadores de los lotes INF-x.y (§5.11)
    ├── .tflint.hcl              configuración de TFLint para infra.yml
    └── pyproject.toml           dependencias de los validadores (grupo `ops`: boto3, httpx)
```

`project/envs/dev/main.tf` solo compone módulos; ningún módulo llama a otro. Las dependencias entre módulos pasan por
variables y outputs (por ejemplo, `computo` recibe los ARN de los secretos y los IDs de los grupos de seguridad).

| Lote | Cómo funciona |
|---|---|
| **INF-0.1 Bootstrap** | Recursos que deben existir antes de cualquier `plan` remoto. El bucket de estado tiene `prevent_destroy` y solo admite TLS. El rol `gha-terraform-plan` (PR) solo puede leer, incluidos los secretos de `dev`, que ya están en el estado; el rol `gha-terraform` (aplicar, con aprobación) tiene permisos amplios pero acotados a la cuenta y región, y todo rol que crea lleva el *permissions boundary* `campus-locator-limite-roles`; el rol `gha-deploy` solo puede publicar imágenes, registrar definiciones de tarea, actualizar los servicios y lanzar `migrate` (§5.8). `bootstrap/configurar_github.py` crea con `gh` las variables del repositorio y el **entorno `dev` de GitHub**: aprobación manual y despliegue solo desde `main` (§3.9) |
| **INF-0.2 Esqueleto** | `envs/dev` con *backend*, proveedor (`default_tags`, `allowed_account_ids`) y los seis módulos, vacíos, ya compuestos en `main.tf`; `data "aws_caller_identity"` (output `cuenta_id`) obliga a configurar el proveedor sin recursos y `data "aws_default_tags"` deja en el estado las etiquetas efectivas. `infra.yml` con `plan` en PR y `apply` aprobado en `main` (§3.9). A partir de aquí todo cambio de infraestructura entra por PR |
| **INF-1.1 Red** | Módulo `red`: VPC, cuatro subredes (las /24 número 0, 1, 10 y 11 de `cidr_vpc`), Internet Gateway, tablas `-publica` y `-privada`, endpoint de S3 en la pública, los cinco grupos de seguridad de §5.7 y el `default` sin reglas. Los grupos se crean aquí (no en cada módulo) y sin reglas en línea: cada regla es un `aws_vpc_security_group_ingress_rule` o `egress_rule`, así las referencias cruzadas no generan ciclos. Entrega a `envs/dev` los IDs que usan INF-1.2 a INF-1.4 (§5.12) y crea los outputs `subredes_tareas` y `sg_migrate` |
| **INF-1.2 Datos y secretos** | RDS en `us-east-1a`; bucket con notificación a `ingesta` (la política de la cola autoriza solo a ese bucket); colas y DLQ; secretos. La **notificación** del bucket (`aws_s3_bucket_notification`) se crea después de la política de la cola, porque S3 valida el destino al guardarla |
| **INF-1.3 Cómputo** | Repositorios ECR (etiquetas inmutables, escaneo básico, conservar 5), clúster, espacio de nombres privado `campus-locator.local`, roles, definiciones de tarea (imagen inicial `:bootstrap`, la imagen de prueba de §5.11, que CI reemplaza), la tarea de validación y servicios con `desired_count = 0` hasta el primer despliegue |
| **INF-1.4 Borde** | HTTP API, VPC Link en las subredes públicas, integración con el servicio Cloud Map `api`, rutas `ANY /{proxy+}` y `POST /v1/auth/login`, throttling y access logs. Expone `api_base_url` |
| **INF-2.1 Escalado y horario** | Acciones programadas (zona `America/Bogota`) para `embedding` y `worker`; política de escalado por pasos de `worker` sobre la profundidad de las colas |
| **INF-3.1 Observabilidad** | Topic SNS, suscripción por correo (hay que confirmarla desde el correo que envía SNS), alarmas de §5.10 y regla de EventBridge de §3.8. Expone `sns_alertas_arn` |
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
| RDS | instancia `campus-locator-dev-db`, base `campus_locator`, usuario `campus_app`, grupo de parámetros `campus-locator-dev-pg17` |
| Bucket del dataset | `campus-locator-dev-dataset-648617469176` |
| Bucket de estado | `campus-locator-tfstate-648617469176` (claves: `bootstrap/terraform.tfstate`, `dev/terraform.tfstate`) |
| Colas SQS | `campus-locator-dev-ingesta`, `campus-locator-dev-ingesta-dlq`, `campus-locator-dev-purga`, `campus-locator-dev-purga-dlq` |
| Topic SNS | `campus-locator-dev-alertas` |
| Secretos | `campus-locator/dev/db`, `campus-locator/dev/jwt`, `campus-locator/dev/admin-inicial` |
| Log groups | `/campus-locator/dev/api`, `/campus-locator/dev/worker`, `/campus-locator/dev/embedding`, `/campus-locator/dev/migrate`, `/campus-locator/dev/validacion`, `/campus-locator/dev/apigw` |
| Streams de log de las tareas | `awslogs-stream-prefix` = nombre del proceso (`api`, `worker`, `embedding`, `migrate`, `validacion`); cada tarea escribe en `<proceso>/app/<id-de-la-tarea>` (p. ej. `embedding/app/0f3c9a…`). Una tarea suelta lanzada con la definición de `embedding` escribe en `/campus-locator/dev/embedding` con el mismo formato |
| Roles IAM | `campus-locator-dev-ecs-ejecucion`, `campus-locator-dev-tarea-api`, `campus-locator-dev-tarea-worker`, `campus-locator-dev-tarea-embedding`, `campus-locator-dev-tarea-migrate`, `campus-locator-gha-terraform-plan`, `campus-locator-gha-terraform`, `campus-locator-gha-deploy` |
| *Permissions boundary* | `campus-locator-limite-roles` (política gestionada; obligatoria en los roles `campus-locator-*` que crea `envs/dev`, §5.8) |
| Presupuesto | `campus-locator-mensual` |
| Alarmas de CloudWatch (INF-3.1) | `campus-locator-dev-api-5xx`, `campus-locator-dev-ingesta-dlq`, `campus-locator-dev-purga-dlq`, `campus-locator-dev-embedding-cpu`, `campus-locator-dev-rds-almacenamiento`, `campus-locator-dev-rds-creditos-cpu` |
| Alarmas de escalado de `worker` (INF-2.1) | `campus-locator-dev-worker-cola-ingesta`, `campus-locator-dev-worker-cola-purga` (subir), `campus-locator-dev-worker-colas-vacias` (bajar) |
| Política de escalado | `campus-locator-dev-worker-cola` (por pasos) |
| Acciones programadas | `campus-locator-dev-embedding-encender`, `campus-locator-dev-embedding-apagar`, `campus-locator-dev-worker-habilitar`, `campus-locator-dev-worker-deshabilitar` |
| Regla de EventBridge | `campus-locator-dev-tarea-detenida` |
| Entorno de GitHub | `dev` (§3.9) |
| Workflows | `infra.yml`, `backend.yml`, `embedding.yml`, `frontend.yml` (§5.9) |

### 5.2 Outputs de Terraform (`envs/dev`)

| Output | Ejemplo / forma | Quién lo usa |
|---|---|---|
| `api_base_url` | `https://abc123.execute-api.us-east-1.amazonaws.com` (sin barra final) | App: `ApiConfig.kt` = este valor + `/v1` |
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
| `sns_alertas_arn` | ARN | depuración |
| `bootstrap: rol_gha_terraform_plan_arn`, `rol_gha_terraform_arn`, `rol_gha_deploy_arn`, `bucket_estado`, `github_repo` | ARN / nombre | variables del repositorio de GitHub (§5.9) y validadores de INF-0.x |
| `bootstrap: limite_roles_arn` | ARN de `campus-locator-limite-roles` | `envs/dev`: `permissions_boundary` de todos sus roles (INF-1.3) |

Ningún servicio lee outputs en tiempo de ejecución: todo lo que necesitan llega por variables de entorno (§5.4).
Los outputs aparecen con el lote que crea su recurso: `api_base_url` con INF-1.4, `sns_alertas_arn` con INF-3.1,
`subredes_tareas` y `sg_migrate` con INF-1.1 y el resto con INF-1.2 e INF-1.3. Desde INF-0.2, `envs/dev` tiene además el output `cuenta_id` (de un
`data "aws_caller_identity"`, que obliga a evaluar el proveedor y su `allowed_account_ids` aunque no haya recursos).

### 5.3 Variables de entrada

`bootstrap/terraform.tfvars` y `envs/dev/terraform.tfvars` (columna «Dónde»). Los dos archivos se versionan: no
contienen secretos. Cada variable de `envs/dev` se declara con el lote que la usa (INF-0.2: `aws_account_id`, `region`,
`proyecto` y `entorno`; INF-1.1: `cidr_vpc`, `az_computo` y `az_secundaria`).

| Variable | Dónde | Valor en `dev` | Notas |
|---|---|---|---|
| `aws_account_id` | ambos | `"648617469176"` | Va a `allowed_account_ids` |
| `region` | ambos | `"us-east-1"` | |
| `proyecto` / `entorno` | ambos | `"campus-locator"` / `"dev"` | Forman el prefijo de §5.1 |
| `cidr_vpc` | `envs/dev` | `"10.20.0.0/16"` | Debe ser una /16 (lo valida el módulo `red`): las subredes son sus /24 número 0, 1, 10 y 11 (§5.1) |
| `az_computo` | `envs/dev` | `"us-east-1a"` | Zona única de tareas y RDS; aloja `publica-a` y `privada-a` |
| `az_secundaria` | `envs/dev` | `"us-east-1b"` | Solo para `publica-b` y `privada-b`: el grupo de subredes de RDS exige dos zonas (ADR-INF-03) |
| `github_repo` | `bootstrap` | `"AlejandroSPosada/4U_project"` | Con las mayúsculas exactas de GitHub. Lo usan los *trust policies* de OIDC; `bootstrap` lo expone como output `github_repo` |
| `github_ids` | `bootstrap` | `{ propietario = 142058005, repositorio = 1362957467 }` | IDs inmutables del `sub` de OIDC (§5.8): el repositorio se creó después del 2026-07-15. `null` = formato clásico |
| `correo_alertas` | ambos | *(el de `bootstrap/terraform.tfvars`)* | Presupuesto (`bootstrap`) y topic de alarmas (`envs/dev`) |
| `presupuesto_usd` | `bootstrap` | `100` | |
| `horario_encendido` | `envs/dev` | `{ zona = "America/Bogota", encender = "cron(0 6 * * ? *)", apagar = "cron(0 22 * * ? *)" }` | Vacío (`null`) = 24/7 |
| `imagen_inicial_tag` | `envs/dev` | `"bootstrap"` | Solo en la primera creación |
| `rds_clase` / `rds_gb` / `rds_gb_max` | `envs/dev` | `"db.t4g.micro"` / `20` / `50` | |
| `pg_version` | `envs/dev` | `"17"` (versión menor ≥ 17.1) | pgvector 0.8.x |

### 5.4 Variables de entorno y secretos por proceso

Valores que **inyecta la infraestructura**. Qué hace cada servicio con ellos lo define su propio §5.

**Secretos** (JSON en Secrets Manager; ECS inyecta cada clave como variable):

| Secreto | Claves | Variable inyectada ← clave | Procesos |
|---|---|---|---|
| `campus-locator/dev/db` | `host`, `port`, `dbname`, `username`, `password` | `DB_PASSWORD` ← `password` (en la tarea de validación, `PGPASSWORD`) | `api`, `worker`, `migrate`, `validacion` |
| `campus-locator/dev/jwt` | `secret` (64 bytes aleatorios codificados en base64; el backend usa la cadena tal cual como clave HMAC, sin decodificarla) | `JWT_SECRET` ← `secret` | `api` |
| `campus-locator/dev/admin-inicial` | `correo`, `password` | `ADMIN_INICIAL_CORREO` ← `correo`, `ADMIN_INICIAL_PASSWORD` ← `password` | `migrate` |

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
| `TORCH_NUM_THREADS` | | | | ✓ | `1` (= vCPU de la tarea) |

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
  tarea de `api` envía con su política de identidad (§5.8).
- El **formato de los mensajes** (incluido cómo tratar el `s3:TestEvent` que S3 envía al configurar la notificación)
  lo define `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.8.
- **Topic SNS** `campus-locator-dev-alertas`: lo publican CloudWatch Alarms y AWS Budgets; suscripción por correo a
  `correo_alertas`. No lo usa ningún servicio.

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
`AlejandroSPosada@142058005/4U_project@1362957467`, variable `github_ids`) y `propietario/repo` en los demás.
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
`update-service` → `wait services-stable` (solo dentro del horario; fuera, el servicio queda con 0 réplicas y toma la
revisión nueva al encender).

**Primer despliegue**: el primer `backend.yml` además pone `desired_count = 1` en `api`; el horario se encarga de
`embedding` y `worker`.

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
| Horario de encendido de `embedding` y habilitación de `worker` | 06:00–22:00 `America/Bogota`, todos los días |
| Escalado de `worker` | sube a 1 con ≥ 1 mensaje visible en `ingesta` o `purga`; baja a 0 tras 15 min en 0 |
| Throttling API Gateway | general: 20 req/s, ráfaga 40 · `POST /v1/auth/login`: 2 req/s, ráfaga 5 |
| Formato de los *access logs* | JSON por línea: `requestId`, `ip`, `requestTime`, `httpMethod`, `routeKey`, `path`, `status`, `responseLength`, `integrationLatency`, `integrationStatus` (`requestId` es el encabezado `apigw-requestid` de la respuesta) |
| Retención de logs | 14 días (todos los log groups) |
| Copias de RDS | 7 días |
| `rds.force_ssl` / `max_connections` | `1` / por defecto de la clase |
| Alarmas | `5xx` de la API > 5 en 5 min · cualquier DLQ con ≥ 1 mensaje · tarea detenida por error (EventBridge, §3.8) · CPU de `embedding` > 90 % por 15 min · RDS `FreeStorageSpace` < 4 GiB (4 294 967 296 bytes) · RDS `CPUCreditBalance` < 20 |
| Presupuesto | 100 USD/mes; avisos 50 % y 80 % real, 100 % pronosticado |
| ECR | conservar las 5 imágenes más recientes por repositorio |

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
- Por ahora se ejecutan desde la máquina de quien cierra el lote, con sus propias credenciales de AWS; ejecutarlos en CI
  es parte de INF-6.1.

**Recursos de apoyo que crea esta carpeta**
- **Imagen de prueba** (`project/pruebas/imagen-prueba/`): imagen mínima que responde 200 en `GET /v1/health` (puerto
  8000) y en `GET /health/ready` (puerto 8080). Se publica en los dos repositorios de ECR con la etiqueta `bootstrap`
  (la de `imagen_inicial_tag`), así los servicios pueden arrancar y validarse antes de que exista el código real. Su
  `ENTRYPOINT` ignora el comando de la definición de tarea, salvo si contiene `app.cli` (tareas `migrate`): en ese caso
  imprime `imagen de prueba: nada que migrar` y sale con 0. Con cualquier otro comando (`api`, `worker`, `embedding`)
  arranca el servidor de prueba en los dos puertos.
- **Tarea de validación** `campus-locator-dev-validacion`: definición de tarea sin servicio, imagen pública
  `public.ecr.aws/docker/library/postgres:17-alpine` (trae `psql` y `nslookup`), con `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER` y `PGPASSWORD` (secreto `db`) y el grupo de seguridad `-api`. Los validadores la lanzan con
  `ecs run-task` sobrescribiendo el comando para comprobar cosas que solo se ven desde dentro de la VPC (base de datos,
  DNS de Cloud Map) y leen el resultado de `/campus-locator/dev/validacion`.

**Validadores de esta carpeta**
- Credenciales: el perfil de AWS de la persona (`AWS_PROFILE`), con lectura sobre la cuenta y escritura sobre los
  recursos de prueba (objetos `dataset/validacion-…`, mensajes en `ingesta`, ejecución de la tarea de validación). El
  script se niega a correr si la cuenta no es `648617469176`.
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
| `errores_aws(accion)` (bloque `with`), `error_aws(exc, accion)`, `codigo_error_aws(exc)` | Traducen errores de boto3: permisos o credenciales → `ErrorConfiguracion`; el resto → `Falla` |
| `avisar(mensaje)`, `resumir(texto, limite)`, `commit_actual()` | Progreso a stderr (stdout queda para `[PASA] …`); recorte de mensajes; commit con `-dirty` |
| `CUENTA`, `REGION`, `PROYECTO`, `DIR_INFORMES` | Constantes (`PROYECTO` y `DIR_INFORMES` son rutas: `project/` y `project/.validacion/`) |
| `PATRON_CREDENCIALES_TERRAFORM`, `PATRON_SIN_INIT` | Expresiones regulares que reconocen en la salida de Terraform un fallo de credenciales (→ código 3) o una copia sin `init` |

Forma de un validador (`validate01.py` la sigue; `validate11.py` es el ejemplo más corto, de solo lectura): `import comun`
(el script se ejecuta como `python src/ops/validate<fase><n>.py`), `main()` crea el `Validador` y devuelve
`correr(cuerpo)`, y el módulo termina con `sys.exit(main())`. `cuerpo(v)`
evalúa primero las precondiciones de credenciales (código 3), luego las de otros lotes (código 2), sin seguir si alguna
falla; limpia restos `validacion-…` de ejecuciones anteriores; registra con `al_limpiar` lo que cree, en cuanto lo crea,
y ejecuta las comprobaciones en el orden del documento de validación.

### 5.12 Código de Terraform de `envs/dev` y de los módulos (convenciones)

Lo que un lote necesita saber para añadir infraestructura sin leer el código existente (INF-0.2 dejó el esqueleto).

**Archivos de `envs/dev`**

| Archivo | Contiene | Regla |
|---|---|---|
| `backend.tf` | *backend* S3 (§3.9): bucket `campus-locator-tfstate-648617469176`, clave `dev/terraform.tfstate`, `use_lockfile`, `encrypt`, `allowed_account_ids` | No se toca |
| `providers.tf` | `terraform { required_version = ">= 1.10" }`, `required_providers` (`hashicorp/aws ~> 6.70`) y `provider "aws"` (`region = var.region`, `allowed_account_ids = [var.aws_account_id]`, `default_tags`) | Un proveedor nuevo se declara aquí (ver «Proveedores y lock») |
| `main.tf` | Solo `data` de cuenta y las llamadas a los seis módulos | Ningún recurso suelto: todo recurso vive en un módulo |
| `variables.tf` / `terraform.tfvars` | Variables de §5.3 que ya usa algún lote, con `type` y `description`; sus valores | Una variable nueva se añade a §5.3 y a los dos archivos en el mismo cambio |
| `outputs.tf` | Outputs de §5.2 | Un output nuevo se añade antes a §5.2 |
| `.terraform.lock.hcl` | Versiones y *hashes* de los proveedores | Versionado; ver «Proveedores y lock» |
| `.gitignore` | Ignora `.terraform/` y los planes; reincluye el lock y `terraform.tfvars` | — |

**Nombres que ya existen en `envs/dev`**

| Nombre | Qué es |
|---|---|
| `var.aws_account_id`, `var.region`, `var.proyecto`, `var.entorno`; `var.cidr_vpc`, `var.az_computo`, `var.az_secundaria` (INF-1.1) | Variables de §5.3 (`aws_account_id` se valida como 12 dígitos) |
| `local.prefijo` | `"${var.proyecto}-${var.entorno}"` = `campus-locator-dev`, sin guion final: el prefijo de §5.1. Está en `main.tf` (INF-1.1); los módulos lo reciben como variable `prefijo` |
| `data.aws_caller_identity.actual` | Cuenta de las credenciales (`.account_id`); alimenta el output `cuenta_id` |
| `data.aws_default_tags.actuales` | Etiquetas efectivas del proveedor; nada lo referencia (lleva `# tflint-ignore: terraform_unused_declarations`) porque solo sirve para que los validadores lean las etiquetas del estado |
| `module.red`, `module.datos`, `module.secretos`, `module.computo`, `module.borde`, `module.observabilidad` | Llamadas a `../../modules/<nombre>`. `module.red` recibe `prefijo`, `region`, `cidr_vpc`, `az_computo` y `az_secundaria` (INF-1.1); los otros cinco, todavía sin argumentos: su lote (§4) les añade entradas y salidas |
| Outputs de `envs/dev` | `cuenta_id` (INF-0.2); `subredes_tareas` = `[module.red.subred_tareas]` y `sg_migrate` = `module.red.grupos_seguridad["api"]` (INF-1.1) |
| Última línea de `main.tf`: `# validacion-0-2 <AAAAMMDD-HHMMSS>` | La escribe y sustituye `validate02.py` (C2 la fusiona en `main`). No se borra ni hace falta moverla: el validador quita la anterior y añade la nueva al final |

**Módulos (`modules/<nombre>/`)**
- Cada uno tiene `main.tf` y `versions.tf` (`terraform { required_version = ">= 1.10" }`). Cuando un módulo usa un
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

**Proveedores y lock**
- `envs/dev/.terraform.lock.hcl` fija hoy `hashicorp/aws` 6.70.0 con *hashes* de `linux_amd64`, `windows_amd64`,
  `darwin_amd64` y `darwin_arm64`. CI usa `init -lockfile=readonly`: si el lock no tiene un proveedor o su *hash*, el
  job falla en `terraform init`.
- Añadir o actualizar un proveedor (p. ej. `hashicorp/random` para `random_password` en INF-1.2):
  ```bash
  cd INFRASTRUCTURA_TERRAFORM/project
  terraform -chdir=envs/dev init -upgrade
  terraform -chdir=envs/dev providers lock -platform=linux_amd64 -platform=windows_amd64 \
    -platform=darwin_amd64 -platform=darwin_arm64
  ```
  y se versiona el lock en el mismo commit.

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

`validate11.py` tiene su propia `terraform_plan()`: lanza `terraform` en otra sesión de procesos (otro grupo en
Windows) con la salida en archivos temporales y, con Ctrl+C, le reenvía la interrupción (SIGINT; CTRL_BREAK en Windows)
y espera hasta 120 s a que suelte el bloqueo, ignorando mientras más Ctrl+C, SIGTERM y SIGHUP. `comun.ejecutar` lo
mataría al instante; y con tuberías, si Python muriera, terraform recibiría SIGPIPE antes de soltar el bloqueo. Usa
`comun._entorno_proceso()` para tener el mismo entorno que `ejecutar`. Con esta ya hay dos variantes de la misma idea:
el próximo validador que lance un `plan` las une en `comun.py` (y actualiza §5.11).

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
escalar a 0 el `worker`.

**ADR-INF-06 — Embeddings en CPU y arquitectura x86_64 (aceptada).**
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

**ADR-INF-11 — Horario de encendido en `dev` y presupuesto con avisos (aceptada).**
`embedding` es el mayor costo variable. Apagarlo de noche ahorra ~13 USD/mes. *Consecuencia:* `/v1/localize` no
funciona fuera de horario; la app debe mostrar el error del backend (`FRONTEND_KOTLIN`, PLAN).

**ADR-INF-12 — *Permissions boundary* obligatorio en los roles que crea `gha-terraform` (aceptada).**
`gha-terraform` necesita crear roles (ECS), y con `PowerUserAccess` más IAM sobre `campus-locator-*` podía crear un
rol propio con `"Action": "*"` y asumirlo: las denegaciones solas no bastaban. Todo rol nuevo exige el boundary
`campus-locator-limite-roles` (sin IAM ni `sts:AssumeRole`, sin salir de la región ni tocar el bucket de estado), que
no se puede quitar ni editar, y `gha-terraform` no puede asumir roles. *Consecuencias:* los roles de `envs/dev`
declaran `permissions_boundary` (output `limite_roles_arn`) y uno sin él falla con `AccessDenied` en
`iam:CreateRole`; los roles `campus-locator-*` ajenos a este diseño quedan fuera del modelo y deben borrarse (R11).

---

## 7. Riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | El gasto supera 100 USD/mes | Media | Alto | Presupuesto con avisos, horario, tamaños mínimos, conservar 5 imágenes en ECR, revisar *Cost Explorer* al cerrar cada lote |
| R2 | Tareas con IP pública expuestas | Baja | Alto | Grupos de seguridad sin entrada desde internet; `embedding` sin permisos de AWS; imágenes base mínimas con escaneo de ECR; grupo `default` sin reglas; `validate11.py` C4 comprueba que ninguna regla entrante de la VPC admite `0.0.0.0/0` ni `::/0` |
| R3 | Caída de `us-east-1a` | Baja | Alto | Aceptado en `dev`; Multi-AZ en `prod` (Fase 6) |
| R4 | `db.t4g.micro` (1 GiB) se queda corto: índice HNSW en memoria, conexiones, créditos de CPU | Media | Medio | Alarma de créditos; el índice cabe holgado hasta ~50 000 vectores de 768 dimensiones; subir a `db.t4g.small` (~23 USD/mes) si hace falta |
| R5 | Contraseña de la base y demás secretos en el estado de Terraform | Media | Medio | Bucket de estado privado, cifrado, versionado y solo TLS. Lo leen el administrador, `gha-terraform` y `gha-terraform-plan`; este último desde cualquier PR del repositorio, que solo abre quien tiene escritura. Aceptado en `dev`; se revisa en INF-6.1 |
| R6 | Imagen de embeddings grande (~2–3 GB): arranque de 1–3 min | Alta | Bajo | *Start period* de 180 s; encender antes de usar; `worker` espera a que `embedding` esté listo |
| R7 | Límite de 30 s y 10 MB de API Gateway | Media | Medio | Fotos del dataset directo a S3; `/v1/localize` limitado a 5 fotos de ≤ 1,5 MB (contrato del backend) |
| R8 | La URL de la API cambia si se recrea la HTTP API, y `ApiConfig.kt` queda desactualizado | Baja | Medio | `prevent_destroy` en la API; dominio propio en Fase 6 |
| R9 | Cuotas por defecto de una cuenta nueva (vCPU de Fargate, etc.) | Baja | Medio | El sistema usa 1,5 vCPU; solicitar aumento si un `apply` falla por cuota |
| R10 | `/v1/localize` es público: abuso que dispara costos | Baja | Medio | *Throttling*; alarma de 5xx; en `prod`, WAF o clave de app |
| R11 | Recursos de un intento anterior (oct-2026) siguen en la cuenta: cuestan y chocan con nombres de §5.1 (bucket del dataset, quizá el *namespace* de Cloud Map o una VPC con `Name = campus-locator-dev-vpc`, que haría fallar C2a de `validate11.py`) | Alta | Medio | Antes del `apply` de INF-1.1, comprobar que no hay otra VPC con ese `Name`; inventario y limpieza del resto antes de INF-1.2 (PLAN §3, nota de INF-1.2; CHANGELOG 0.3.0) |
| R12 | El repositorio es público: los logs de Actions y los comentarios del `plan` los puede leer cualquiera | Alta | Bajo | Terraform oculta los valores `sensitive` (contraseñas, secretos) en el `plan` y en los logs; ningún paso imprime el estado ni credenciales; todo output con un dato sensible se declara `sensitive`; los PR desde *forks* no ejecutan el `plan`. Lo que queda visible (IDs, ARN, URL) no da acceso por sí solo |

---

## 8. Referencias cruzadas

- Contratos del backend (API, base de datos, mensajes, comandos): `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.
- Contratos del servicio de embeddings: `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5.
- App y puentes WebView: `FRONTEND_KOTLIN/docs/ARCHITECTURE.md` §5.
- Historias de usuario (catálogo único): `FRONTEND_KOTLIN/docs/PLAN.md` §5.
