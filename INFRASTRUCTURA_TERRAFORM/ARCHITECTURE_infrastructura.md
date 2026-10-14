# ARCHITECTURE — Infraestructura como código (Campus Locator)

Plan de la infraestructura de **Campus Locator** con **Terraform**. Complementa el `ARCHITECTURE.md` de la
app Android (`FRONTED_KOTLIN/`), que describe qué hace el sistema y qué endpoints necesita (sección 3 de ese
documento). Este documento describe **dónde corre cada pieza, cómo se conectan y cómo se crea todo con código**.

> **Estado (2026-10-13):** las **fases 0 a 3 para `dev` están aplicadas en AWS** (`bootstrap/` y `envs/dev/`: 65
> recursos, con `encendido=false`, o sea backend y embedding creados pero con 0 tareas). Falta construir y subir las
> imágenes, habilitar `pgvector` y comprobar el arranque real de los servicios (12.1, 12.2, 12.13).
> Las fases 4 a 8 siguen sin hacerse. Los supuestos marcados con ⚠ son decisiones o datos por confirmar; el plan
> asume **AWS** porque `FRONTED_KOTLIN/ARCHITECTURE.md` ya habla de S3 con URLs prefirmadas.
>
> **Para quien continúe (persona o IA):** este archivo es la única fuente que hace falta. La **sección 11** es el
> catálogo del código existente (cada módulo, sus variables, salidas y cuidados) y la **sección 12** lista lo
> pendiente y los riesgos conocidos; no hace falta abrir los `.tf` para saber qué hay.

---

## 1. Dónde vive este folder

**Respuesta corta: `INFRASTRUCTURA_TERRAFORM/` es un folder hermano de los otros tres, al mismo nivel, dentro de
un único repositorio (monorepo). No va dentro de ninguno de ellos ni "encima" de ellos como código.**

```
campus-locator/                      ← raíz del repositorio Git (un solo repo)
├── .github/workflows/               ← CI/CD de TODO el repo (GitHub exige que viva en la raíz)
├── FRONTED_KOTLIN/                  ← app Android (Kotlin + Compose)
├── BACKEND_FASTAPI/                 ← API REST (FastAPI)
├── SERVICE_EMBEDDING/               ← servicio DINOv2 (embeddings)
├── INFRASTRUCTURA_TERRAFORM/        ← ESTE folder
├── README.md
└── .gitignore
```

Por qué hermano y no dentro de otro:

| Opción | Problema |
|---|---|
| Dentro de `BACKEND_FASTAPI/` | La infra despliega **también** el embedding service, la base de datos y el almacenamiento. No pertenece solo al backend |
| "Encima" de los demás (la raíz es la infra) | Mezcla el código de la app con archivos de Terraform y complica los `.gitignore`, los pipelines y los permisos |
| **Hermano (recomendado)** | Ciclo de vida, permisos y *state* propios; los servicios siguen siendo desplegables por separado; se ve de un vistazo qué infra tiene cada pieza |

Regla de oro: **cada servicio contiene su propio `Dockerfile`; Terraform solo sabe qué imagen ejecutar** (una URL de
ECR + una etiqueta). Terraform no construye imágenes ni compila la app.

> ⚠ **No guardar este proyecto en Google Drive** (`G:\My Drive\...`). Terraform crea una carpeta `.terraform/` con
> cientos de MB y archivos de estado; el mismo problema de permisos que dio Gradle (`errno 5`) aparecerá aquí.
> Usar una carpeta local (por ejemplo `C:\dev\campus-locator`) y respaldar con Git. El *state* de Terraform **nunca**
> se guarda en el disco: va a un bucket remoto (sección 6).

---

## 2. Qué se despliega

Resumen de los componentes que pide el sistema (ver sección 3 de `FRONTED_KOTLIN/ARCHITECTURE.md`) y su recurso:

| Necesidad del sistema | Recurso en AWS | Notas |
|---|---|---|
| API REST (`/localize`, `/places`, `/alerts`, `/auth/login`, `/admin/*`, `/collect/*`) | **ECS Fargate** (servicio `backend`) | Contenedor de `BACKEND_FASTAPI/`. Health check `GET /health` (la app ya prevé ese endpoint) |
| Embeddings DINOv2 | **ECS Fargate** (servicio `embedding`), CPU al principio | Contenedor de `SERVICE_EMBEDDING/`. **Solo accesible desde el backend**, nunca desde internet |
| Dataset: foto + embedding + coordenada + orientación + `video_id` | **RDS PostgreSQL + extensión `pgvector`** | Un solo motor para metadatos (usuarios, lugares, alertas, videos) **y** búsqueda por similitud. Suficiente para miles de fotos |
| Archivos de las fotos | **S3** bucket privado | URLs prefirmadas de vida corta, como ya describe 7.11 de la app |
| Fotos de escaneo de usuarios públicos | S3 bucket aparte con **expiración automática** | Depende de la decisión de privacidad (⚠ 9.6) |
| Autenticación con roles `USER` / `ADMIN` | JWT firmado por el backend; secreto en **Secrets Manager** | El contrato de la app es `POST /auth/login` → token + rol |
| Entrada HTTPS | **ALB** + certificado **ACM** (+ dominio) | Android bloquea HTTP sin cifrar desde la API 28: **hace falta HTTPS** (⚠ 9.3) |
| Imágenes de contenedor | **ECR** (un repositorio por servicio) | |
| Logs y alarmas | **CloudWatch** | |
| Mapa base | — | Va directo del `WebView` a OpenStreetMap; **no pasa por la infra** (sección 2.6 de la app) |

### 2.1 Diagrama

```
                       Internet (HTTPS)
                              │
  App Android ───────────►  ALB  (ACM + dominio)
                              │  health: GET /health
                    ┌─────────▼──────────┐
 subredes públicas  │                    │
 ────────────────── │   ECS Fargate      │ ──────────────────────────────
 subredes privadas  │   backend (FastAPI)│
                    └───┬────────┬───────┘
                        │        │  HTTP interno (Cloud Map / SG)
                        │        ▼
                        │   ECS Fargate · embedding (DINOv2)
                        │
            ┌───────────┴─────────┐
            ▼                     ▼
   RDS PostgreSQL + pgvector     S3 (fotos del dataset, fotos de escaneo)
            │
   Secrets Manager  ·  CloudWatch  ·  ECR
```

### 2.2 Flujos que la infra debe soportar

1. **Ubicarse** (`POST /localize`, 5 fotos): app → ALB → backend → embedding (5 embeddings) → consulta `pgvector`
   → respuesta. La latencia total manda: backend y embedding **en la misma región y misma VPC**.
2. **Recolección** (`POST /collect/videos/{id}/images`): app → backend → S3 (archivo) + embedding → fila en Postgres.
3. **Eliminar un video** (`DELETE /admin/videos/{id}`): borra filas, embeddings y objetos de S3 en una sola operación
   del backend. La infra solo concede el permiso `s3:DeleteObject` al rol del backend.
4. **Alertas** (`GET /alerts`): lectura simple de Postgres; la app las cachea localmente.

---

## 3. Estructura del folder

```
INFRASTRUCTURA_TERRAFORM/
├── ARCHITECTURE.md                  ← este documento
├── README.md                        ← cómo ejecutar (init / plan / apply)
│
├── bootstrap/                       ← se ejecuta UNA vez, con state local
│   ├── main.tf                      ← bucket del state, rol OIDC de GitHub
│   └── outputs.tf
│
├── modules/                         ← piezas reutilizables, sin valores fijos
│   ├── network/                     ← VPC, subredes, tablas de rutas, (NAT opcional)
│   ├── ecr/                         ← repositorios de imágenes + política de limpieza
│   ├── storage/                     ← buckets S3 (cifrado, privados, ciclo de vida)
│   ├── database/                    ← RDS PostgreSQL, grupo de parámetros, pgvector
│   ├── secrets/                     ← Secrets Manager (JWT, etc.)
│   ├── ecs_cluster/                 ← cluster + Cloud Map (nombres internos)
│   ├── ecs_service/                 ← servicio genérico: lo usan backend Y embedding
│   ├── alb/                         ← balanceador, listeners, target groups
│   ├── dns_cert/                    ← Route 53 + ACM (si hay dominio)            [PENDIENTE, fase 4]
│   ├── iam_cicd/                    ← rol que asume GitHub Actions (OIDC)        [NO CREADO: hoy vive en bootstrap/]
│   └── observability/               ← log groups, alarmas, dashboard             [PENDIENTE, fase 6]
│
└── envs/                            ← una carpeta = un ambiente = un state
    ├── dev/
    │   ├── backend.tf               ← state remoto de dev
    │   ├── main.tf                  ← ensambla los módulos
    │   ├── variables.tf
    │   ├── terraform.tfvars         ← valores de dev (sin secretos)
    │   └── outputs.tf
    └── prod/                        ← misma forma, otros valores                 [PENDIENTE, fase 7]
```

> Existen hoy: `bootstrap/`, los módulos `network`, `ecr`, `storage`, `database`, `secrets`, `ecs_cluster`,
> `ecs_service` y `alb`, y `envs/dev/`. Más `.gitignore` y `README.md` (que solo resume los pasos de ejecución;
> el detalle está aquí). Archivos por módulo: `main.tf`, `variables.tf`, `outputs.tf`.

Convenciones:
- **Módulos sin lógica de ambiente:** reciben variables y devuelven *outputs*. Toda diferencia entre `dev` y `prod`
  (tamaños, réplicas, retención) está en `terraform.tfvars`.
- **Un `ecs_service` genérico** sirve a backend y embedding: cambian la imagen, el puerto, la CPU/memoria, las
  variables de entorno y si está detrás del ALB o es interno.
- Versiones fijadas: `required_version` de Terraform y `required_providers` con versión (`~>`) en cada raíz;
  `.terraform.lock.hcl` **se sube a Git**.
- Nombres: `campus-locator-<ambiente>-<recurso>`; *tags* obligatorios `Project`, `Env`, `ManagedBy = terraform`.
- `terraform fmt` y `terraform validate` en CI; `tflint` y un escáner de seguridad (`trivy config`) como
  comprobación adicional.

---

## 4. Contratos entre las carpetas

Esta sección existe para que quien trabaje en una carpeta no tenga que abrir las otras.

### 4.1 Infra → `BACKEND_FASTAPI`

Terraform inyecta estas **variables de entorno** en el contenedor. El backend debe leerlas con estos nombres.

| Variable | Origen | Contenido |
|---|---|---|
| `APP_ENV` | `terraform.tfvars` | `dev` o `prod` |
| `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME` | output del módulo `database` | Conexión a Postgres |
| `DATABASE_SECRET_ARN` | RDS con contraseña administrada | ARN del secreto con usuario y contraseña; el backend lo lee con el SDK. **La contraseña no pasa por Terraform ni por el state** |
| `S3_BUCKET_DATASET` | módulo `storage` | Bucket de las fotos del dataset |
| `S3_BUCKET_SCANS` | módulo `storage` | Bucket de las fotos de escaneo |
| `EMBEDDING_SERVICE_URL` | módulo `ecs_cluster` | Ej. `http://embedding.campus.internal:8001` (nombre interno, Cloud Map) |
| `JWT_SECRET_ARN` | módulo `secrets` | ARN del secreto para firmar los tokens |
| `AWS_REGION` | `terraform.tfvars` | Región |

Permisos que Terraform concede al rol del contenedor backend: leer/escribir/borrar en los dos buckets, leer los dos
secretos, escribir logs. **Nada más.**

Requisitos que la infra le pide al backend:
- `GET /health` → `200` sin autenticación (health check del ALB).
- Escuchar en `0.0.0.0:8000`.
- Migraciones del esquema con **Alembic** (la infra crea la base y habilita `CREATE EXTENSION vector`; **no** crea
  tablas).

### 4.2 Infra → `SERVICE_EMBEDDING`

| Variable | Contenido |
|---|---|
| `APP_ENV` | `dev` o `prod` |
| `MODEL_NAME` | Variante de DINOv2 (⚠ 9.4: `dinov2_vits14` / `vitb14`) |
| `PORT` | `8001` |

- Sin acceso a internet: **los pesos del modelo van dentro de la imagen** (se descargan al construirla, no al
  arrancar).
- `GET /health` → `200` solo cuando el modelo ya cargó.
- Su *security group* solo acepta tráfico del *security group* del backend.
- Sin permisos de AWS (no necesita S3 ni secretos): recibe los bytes de la imagen y devuelve el vector.

### 4.3 Infra → `FRONTED_KOTLIN`

La app solo necesita **una cosa**: la URL base de la API.

- Output de Terraform: `api_base_url` (ej. `https://api.dev.<dominio>`).
- Hoy vive en `ApiConfig.kt`. Recomendado: leerla de `BuildConfig` con un valor distinto por `buildType`
  (`debug` → dev, `release` → prod) en `build.gradle.kts`.
- Regla: **HTTPS siempre**; la app no habilita tráfico sin cifrar.

### 4.4 Qué entra y qué no en Terraform

| Sí | No |
|---|---|
| Red, ALB, ECS, RDS, S3, ECR, IAM, secretos, logs, DNS | Compilar la app Android |
| Habilitar `pgvector` en la base | Crear tablas (lo hace Alembic desde el backend) |
| Crear el secreto del JWT (con `random_password`) | Construir las imágenes Docker (lo hace CI) |
| Variables de entorno de los contenedores | Subir el dataset de fotos (lo hace la app/backend) |
| | Mapa base (OpenStreetMap, externo) |

---

## 5. Seguridad

- **S3:** todos los buckets con *Block Public Access*, cifrado en reposo (SSE-S3 o KMS), *versioning* solo en el
  bucket del state, y política que exige TLS (`aws:SecureTransport`).
- **Base de datos:** en subredes privadas, sin IP pública, acceso solo desde el *security group* del backend,
  cifrada, con copias automáticas (7 días en dev, 14+ en prod) y `deletion_protection = true` en prod.
- **Contraseña de RDS:** `manage_master_user_password = true` (la gestiona AWS en Secrets Manager); evita que la
  contraseña quede en el *state*.
- **Security groups encadenados:** `internet → ALB → backend → embedding` y `backend → RDS`. Ningún otro camino.
- **IAM de mínimo privilegio:** un rol de tarea por servicio; un rol de ejecución para tirar imágenes y escribir logs.
- **Secretos:** solo en Secrets Manager; jamás en `terraform.tfvars`, en variables de entorno en claro ni en Git.
- **State:** bucket cifrado, con acceso restringido y *versioning*; el state **contiene datos sensibles** aunque
  evitemos las contraseñas (ARNs, nombres, endpoints).
- **CI sin llaves largas:** GitHub Actions asume un rol por **OIDC**; no hay `AWS_ACCESS_KEY_ID` guardada.
- **Privacidad (decisión 7 de la app):** el bucket de fotos de escaneo tiene una regla de ciclo de vida que borra los
  objetos a las 24 h (valor por definir). Si se decide no almacenar nada, se elimina el bucket.

---

## 6. State y ambientes

- **State remoto** en S3 (bucket creado por `bootstrap/`), uno por ambiente (`envs/dev/terraform.tfstate`,
  `envs/prod/terraform.tfstate`). Bloqueo con `use_lockfile = true` (Terraform ≥ 1.10) o, en versiones anteriores,
  una tabla DynamoDB.
- **Dos ambientes: `dev` y `prod`.** Mismo código de módulos, distinto `terraform.tfvars`:

| Parámetro | `dev` | `prod` |
|---|---|---|
| Réplicas backend / embedding | 1 / 1 | 2 / 2 |
| RDS | instancia pequeña, una zona | instancia mayor, Multi-AZ |
| Retención de logs | 7 días | 30–90 días |
| `deletion_protection` | no | sí |
| Costo | el mínimo posible | el necesario |

- `terraform destroy` debe ser seguro en `dev` (se puede apagar fuera de horario para ahorrar); en `prod` está
  protegido.

---

## 7. CI/CD (GitHub Actions)

Los *workflows* viven en `.github/workflows/` (raíz) y filtran por carpeta (`paths:`).

| Workflow | Se dispara con | Qué hace |
|---|---|---|
| `infra-plan` | PR que toca `INFRASTRUCTURA_TERRAFORM/**` | `fmt`, `validate`, `tflint`, `plan`; publica el plan como comentario del PR |
| `infra-apply-dev` | merge a `main` | `apply` en `dev` |
| `infra-apply-prod` | manual (con aprobación) | `apply` en `prod` |
| `backend-deploy` | cambios en `BACKEND_FASTAPI/**` | construye la imagen, la sube a ECR y actualiza el servicio ECS |
| `embedding-deploy` | cambios en `SERVICE_EMBEDDING/**` | ídem para el embedding |

Despliegue de la aplicación: el servicio ECS se crea con Terraform con `lifecycle { ignore_changes =
[task_definition] }`, y **CI registra una nueva definición de tarea con la etiqueta de la imagen** (el SHA del
commit). Así Terraform no revierte los despliegues y los cambios de código no necesitan `terraform apply`.

---

## 8. Plan de implementación por fases

Cada fase termina con un criterio de aceptación comprobable.

| Fase | Contenido | Aceptación | Estado |
|---|---|---|---|
| **0. Bootstrap** | `bootstrap/`: bucket del state, rol OIDC de GitHub. Proyecto movido fuera de Google Drive | `terraform init` en `envs/dev` usa el state remoto | **Hecha** (2026-10-13): `apply` de `bootstrap/` e `init` de `envs/dev` con el state remoto. El proyecto sigue en OneDrive (12.12) |
| **1. Red y almacenamiento** | `network`, `ecr`, `storage` (+ alarma de Budgets) | `terraform plan` limpio; buckets privados verificados | **Aplicada** (2026-10-13): plan limpio y `apply` completo; falta verificar a mano que los buckets sean privados |
| **2. Datos** | `database` (RDS + `pgvector`), `secrets` | Se conecta desde dentro de la VPC y `CREATE EXTENSION vector` funciona | **Aplicada** (RDS PostgreSQL 16.15 creada); falta la conexión desde la VPC y el `CREATE EXTENSION`, que no lo hace Terraform (12.1) |
| **3. Cómputo** | `ecs_cluster`, `ecs_service` × 2, `alb` | `GET /health` del backend responde por el ALB; el embedding responde solo desde el backend | **Aplicada con 0 tareas** (`encendido=false`); faltan los `Dockerfile` y las imágenes. `/health` por el ALB sin comprobar |
| **4. Borde HTTPS** | `dns_cert` (o CloudFront si no hay dominio, ⚠ 9.3) | La app Android en un teléfono real llama a `https://…` | Pendiente. El `alb` ya acepta `certificate_arn` |
| **5. CI/CD** | Los cinco workflows de la sección 7 | Un cambio en `BACKEND_FASTAPI/` llega a `dev` sin intervención manual | Pendiente (el rol OIDC ya está en `bootstrap/`) |
| **6. Observabilidad** | `observability`: logs, alarmas (5xx, CPU, espacio de RDS, tareas caídas), dashboard | Una alarma de prueba llega al correo | Pendiente (los log groups ya los crea `ecs_service`) |
| **7. Prod** | `envs/prod` con las diferencias de la sección 6 | Prueba completa: ubicarse → recolectar → eliminar video | Pendiente |
| **8. (Opcional) GPU / lotes** | Capacidad EC2 con GPU o trabajo por lotes para indexar | Procesar un video de 200 fotos en un tiempo aceptable | Pendiente |

Orden de trabajo recomendado: **0 → 1 → 2 → 3** primero en `dev`, y no empezar la fase 5 hasta que `BACKEND_FASTAPI`
tenga un `Dockerfile` y un `/health` funcionales.

---

## 9. Decisiones abiertas (por definir)

Cada una trae una recomendación para poder avanzar.

> **Valores que el código de `dev` ya asumió** (se usó la recomendación de cada punto; siguen abiertas hasta que
> las confirmes): 9.1 AWS · 9.2 `us-east-1` · 9.3 **sin resolver** (ALB en HTTP solo para pruebas) · 9.4 CPU con
> `dinov2_vitb14` (modelo "medio"), 2 vCPU / 4 GB · 9.5 `pgvector` en el mismo RDS · 9.6 bucket de escaneos creado,
> expira a 1 día · 9.7 sin NAT en dev · 9.8 JWT propio (secreto en Secrets Manager) · 9.9 subida vía backend ·
> 9.10 sin definir · 9.11 presupuesto de 40 USD/mes, creado solo si se da un correo.
>
> **Contexto de uso (2026-10-12):** proyecto universitario, 1 o 2 clientes como máximo y encendido solo durante
> desarrollo y exposición. Por eso hay un **interruptor de apagado** (11.5) y un solo ambiente real (`dev`); ver 12.6 y 12.10.

1. **⚠ Proveedor de nube.** Se asume AWS. Si la universidad ofrece créditos de otro proveedor (Azure, GCP), la
   estructura de módulos se mantiene pero cambian los recursos.
2. **⚠ Región.** `us-east-1`: más barata y con todos los servicios. `sa-east-1` (São Paulo): menor latencia desde
   Colombia, más cara. *Recomendado:* `us-east-1` para empezar; la latencia de 5 fotos hacia DINOv2 pesa más que el
   viaje de red.
3. **⚠ Dominio y HTTPS.** Android exige HTTPS. Opciones: (a) comprar un dominio (Route 53, ~12 USD/año) + ACM;
   (b) sin dominio, poner **CloudFront** delante del ALB (da un `*.cloudfront.net` con HTTPS). *Recomendado:* (a).
4. **⚠ CPU o GPU para DINOv2.** Con 5 fotos por consulta, un `vits14` o `vitb14` en CPU Fargate puede bastar; la
   indexación de un video completo (hasta 200 fotos) es lo que más lo exige. *Recomendado:* empezar en CPU y medir
   (fase 8 si hace falta).
5. **⚠ Dónde guardar los vectores.** *Recomendado:* `pgvector` en el mismo Postgres (un solo sistema, transacciones
   entre metadatos y vectores, y borrar un video borra todo junto). Alternativas (OpenSearch, un índice FAISS en
   memoria) solo se justifican si el dataset crece a cientos de miles de fotos.
6. **⚠ Privacidad de las fotos de usuarios públicos** (decisión 7 de la app). Determina si existe el bucket de
   escaneos y con qué retención.
7. **⚠ NAT Gateway o no.** Un NAT cuesta ~32 USD/mes fijos. En `dev`: tareas en subredes públicas con *security
   groups* cerrados (sin NAT) y RDS privada; en `prod`: subredes privadas + NAT o *VPC endpoints* de ECR, S3, Logs y
   Secrets Manager. *Recomendado:* sin NAT en `dev`.
8. **⚠ Autenticación.** *Recomendado:* JWT propio del backend (coincide con el contrato actual `POST /auth/login`).
   Cognito solo si se necesita recuperación de contraseña, correo verificado u otros proveedores.
9. **⚠ Subida de fotos.** Hoy el plan es app → backend → S3. Con videos de 200 fotos podría convenir **subida directa
   a S3 con URL prefirmada** (la app sube; el backend solo registra y procesa). *Recomendado:* empezar por el
   backend y migrar si la subida es lenta.
10. **⚠ Moderación y respaldo.** Frecuencia de copias y retención del dataset (es el activo más valioso del proyecto);
    quién puede ejecutar `apply` en `prod`.
11. **⚠ Presupuesto.** Definir un tope mensual y crear una **alarma de AWS Budgets** desde la fase 1.

---

## 10. Cómo mantener este documento

- Cambios de infraestructura → actualizar este archivo **en el mismo PR**.
- Un nuevo módulo → añadirlo a la sección 3 y, si expone o consume variables de otra carpeta, a la sección 4.
- Un nuevo endpoint o servicio en `BACKEND_FASTAPI/` o `SERVICE_EMBEDDING/` que necesite una variable de entorno →
  añadirla a la tabla correspondiente de la sección 4 **antes** de usarla.
- Cuando una decisión de la sección 9 se tome, moverla a la sección donde aplique y tacharla de la lista.
- **Cualquier cambio en un `.tf` actualiza su entrada en la sección 11 en el mismo cambio**, y lo que quede por
  hacer o por confirmar va a la sección 12. Lo marcado con ⚠ no está verificado: confirmarlo antes de depender de ello.

---

## 11. Catálogo del código existente

> Escrito el 2026-10-12 y corregido el 2026-10-13 tras el primer `validate`, `plan` y `apply` de `dev` (65 recursos
> creados, con `encendido=false`). Lo que **ya se observó**: que el código valida, planifica y se aplica. Lo que
> **no** se ha observado: el arranque de los servicios ECS, `/health` por el ALB, la conexión a RDS, `pgvector` y los
> scripts de apagado; esos comportamientos son los que el código pretende.
> Convención de todos los módulos: `main.tf` + `variables.tf` + `outputs.tf`, sin lógica de ambiente.

### 11.1 Cómo se ejecuta

```bash
# 1) Una sola vez (state local)
cd bootstrap
cp terraform.tfvars.example terraform.tfvars      # poner state_bucket_name y github_repo ("owner/repo")
terraform init && terraform apply
terraform output state_bucket                     # copiar a envs/dev/backend.tf (el bloque backend no admite variables)

# 2) Ambiente dev
cd ../envs/dev
terraform init
terraform fmt -recursive ../..
terraform validate
terraform plan
terraform apply
```

- Requiere Terraform **>= 1.10** (el state usa `use_lockfile`) y credenciales de AWS. Subir `.terraform.lock.hcl` a Git.
- En **Windows PowerShell 5.1** `&&` no es un separador válido: ejecutar `terraform init` y `terraform apply` en líneas
  separadas (o encadenar con `;`). Cada comando se ejecuta **dentro de su carpeta** (`bootstrap/` o `envs/dev/`): en la
  raíz del repositorio `terraform output` no encuentra nada.
- Como todavía no hay imágenes en ECR, el primer `apply` de `dev` se hizo con los servicios apagados:
  `terraform apply -var "encendido=false"`.
- Valores usados en `bootstrap/` (2026-10-13): `state_bucket_name = "4uproject-eafit-tfstate"` y
  `github_repo = "AlejandroSPosada/4U_project"`. Región de la infraestructura: `us-east-1` (la AWS CLI local está en
  `us-east-2`; ver 12.11).
- `.gitignore` excluye `.terraform/`, `*.tfstate*`, `*.tfplan`, `*.auto.tfvars` y `bootstrap/terraform.tfvars`;
  `terraform.tfvars` de `envs/dev` **sí** se sube (no lleva secretos).
- Proveedores: `hashicorp/aws ~> 5.80` (bootstrap y dev) y `hashicorp/random ~> 3.6` (el módulo `secrets` lo declara
  y `envs/dev` también).

### 11.2 `bootstrap/`

| Pieza | Detalle |
|---|---|
| Variables | `project` (`campus-locator`), `region` (`us-east-1`), **`state_bucket_name`** (obligatoria, global única; sugerido `campus-locator-tfstate-<id de cuenta>`), **`github_repo`** (obligatoria, `owner/repo`), `github_ci_policy_arns` (por defecto `PowerUserAccess` + `IAMFullAccess`) |
| Bucket del state | `prevent_destroy`, versionado, SSE AES256, bloqueo de acceso público, borra versiones antiguas a los 90 días, política que deniega todo sin TLS |
| OIDC de GitHub | Proveedor `token.actions.githubusercontent.com` y rol **`<project>-github-ci`**; solo lo asume `repo:<github_repo>:*` (cualquier rama o entorno del repositorio) |
| Salidas | `state_bucket`, `github_ci_role_arn` |
| State | **Local** (`terraform.tfstate` en esta carpeta, ignorado por Git): conservarlo o importarlo; perderlo deja bucket y rol huérfanos |

### 11.3 Módulos

| Módulo | Variables (por defecto) | Qué crea | Salidas |
|---|---|---|---|
| `network` | `name`, `region`, `vpc_cidr` (`10.20.0.0/16`), `az_count` (2; validación ≥ 2), `enable_nat_gateway` (`false`) | VPC con DNS; `az_count` subredes **públicas** (`cidrsubnet(vpc, 8, i)`) y **privadas** (`cidrsubnet(vpc, 8, i+10)`); IGW; una tabla de rutas pública y una **única** privada; NAT + EIP **solo si** `enable_nat_gateway` (uno solo, en la primera subred pública); endpoint de S3 (gateway, gratis) en ambas tablas | `vpc_id`, `vpc_cidr`, `public_subnet_ids`, `private_subnet_ids` |
| `ecr` | `name`, `repositories` (`["backend","embedding"]`), `keep_images` (10), `force_delete` (`false`) | Repositorios **`<name>/<servicio>`** (etiquetas mutables, escaneo al subir, SSE AES256) y política que conserva las últimas `keep_images` imágenes | `repository_urls` (mapa servicio → URL), `repository_arns` |
| `storage` | `name`, `account_id`, `create_scans_bucket` (`true`), `scans_expire_days` (1), `force_destroy` (`false`) | Bucket **`<name>-dataset-<cuenta>`** y, opcional, **`<name>-scans-<cuenta>`**. Ambos: sin acceso público, SSE-S3, `BucketOwnerEnforced`, política que exige TLS. Escaneos: expiran a `scans_expire_days` y abortan multiparte a 1 día. Dataset: aborta multiparte a 7 días. **Sin versionado** | `dataset_bucket`, `dataset_bucket_arn`, `scans_bucket` (`""` si no existe), `scans_bucket_arn` (`""`), `bucket_arns` |
| `database` | `name`, `vpc_id`, `subnet_ids`, `engine_major_version` (`16`), `engine_version` (`16.15`, ver 12.4), `instance_class` (`db.t4g.micro`), `allocated_storage_gb` (20), `max_allocated_storage_gb` (100), `db_name` (`campus`), `master_username` (`campus_admin`), `multi_az` (`false`), `backup_retention_days` (7), `deletion_protection` (`false`) | Grupo de subredes, **security group sin reglas de entrada**, grupo de parámetros (`rds.force_ssl = 1`), instancia PostgreSQL gp3 cifrada, no pública, con `manage_master_user_password = true`. Con `deletion_protection = true` toma copia final; sin ella, no. `apply_immediately` = lo contrario de `deletion_protection` | `host`, `port`, `name`, `secret_arn`, `security_group_id` |
| `secrets` | `name`, `recovery_window_in_days` (7) | `random_password` de 64 caracteres (sin símbolos) y el secreto **`<name>/jwt-secret`** con ese valor | `jwt_secret_arn` |
| `ecs_cluster` | `name`, `vpc_id`, `namespace` (`campus.internal`), `container_insights` (`false`) | Clúster **`<name>-cluster`** y espacio de nombres DNS privado de Cloud Map | `cluster_arn`, `cluster_name`, `namespace_id`, `namespace_name` |
| `alb` | `name`, `vpc_id`, `vpc_cidr`, `public_subnet_ids`, `target_port` (8000), `health_check_path` (`/health`), `certificate_arn` (`null`), `idle_timeout` (60), `deletion_protection` (`false`) | SG (entrada 80 desde internet, 443 solo con certificado; **salida solo hacia el CIDR de la VPC**), ALB público **`<name>-alb`**, target group **`<name>-backend`** (tipo `ip`, health 200 cada 30 s, 2 sanos / 3 no sanos). **Sin certificado:** el puerto 80 reenvía al backend. **Con certificado:** 80 redirige (301) a 443 y 443 reenvía (política TLS 1.3/1.2 `ELBSecurityPolicy-TLS13-1-2-2021-06`) | `dns_name`, `zone_id`, `security_group_id`, `target_group_arn`, `https_enabled` |
| `ecs_service` | `name`, `service_name`, `cluster_arn`, `vpc_id`, `subnet_ids`, `assign_public_ip` (`false`), `image`, `container_port`, `cpu` (512), `memory` (1024), `cpu_architecture` (`X86_64`), `desired_count` (1), `environment` (mapa, `{}`), `ingress_security_group_ids` (`[]`), `target_group_arn` (`null`), `health_check_grace_seconds` (60), `enable_service_discovery` (`false`), `service_discovery_namespace_id` (`null`; solo se usa si `enable_service_discovery = true`), `attach_task_policy` (`false`), `task_policy_json` (`null`), `log_retention_days` (7) | Log group `/ecs/<name>-<servicio>`; **rol de ejecución** (`-exec`, política `AmazonECSTaskExecutionRolePolicy`) y **rol de tarea** (`-task`, con política en línea solo si `attach_task_policy`); SG (entrada TCP al puerto del contenedor solo desde los SG indicados, salida abierta); definición de tarea Fargate `awsvpc` con **un** contenedor llamado como `service_name` y logs `awslogs`; registro en Cloud Map (A, TTL 10 s, `MULTIVALUE`) solo si `enable_service_discovery = true`; servicio ECS con disyuntor de despliegue (reversión automática), `load_balancer` solo si hay `target_group_arn` y `ignore_changes = [task_definition]` | `security_group_id`, `service_name`, `task_role_arn`, `execution_role_arn`, `log_group_name` |

Cuidados de los módulos:
- **Límite de nombres del ALB y del target group: 32 caracteres.** Con `campus-locator-<env>` hoy caben (`campus-locator-prod-backend` = 27), pero un prefijo más largo rompe el `apply`.
- `attach_task_policy` es un booleano aparte (en vez de comprobar si `task_policy_json` es `null`) porque ese JSON sale de un `data` y su nulidad no se conoce al planificar.
- **Nunca decidir un `count` o `for_each` comparando con `null` un valor que sale de otro recurso** (`namespace_id`, ids,
  ARNs): no se conoce al planificar y `plan` falla con `Invalid count argument`. Por eso `aws_service_discovery_service`
  usa el booleano `enable_service_discovery` y no `service_discovery_namespace_id != null` (fallo hallado y corregido
  el 2026-10-13). Es el mismo patrón que `attach_task_policy`.
- `ingress_security_group_ids` se recorre con `count`, no con `for_each`, por la misma razón (los ids no se conocen al planificar). Cambiar el **orden** de la lista recrea reglas.
- El contenedor **no define** `healthCheck` propio y **no inyecta secretos** como variables: el backend lee los secretos con el SDK usando su rol de tarea.
- El rol de ejecución solo tira imágenes y escribe logs; los permisos de la app van en el rol de tarea.
- `health_check_grace_period_seconds` solo se fija cuando hay target group (ECS lo rechaza en servicios sin balanceador).
- El módulo `network` crea **una** tabla de rutas privada y **un** NAT: no hay alta disponibilidad de salida (aceptable en dev).
- El SG de la base no trae reglas: la regla `backend → 5432` la agrega `envs/dev` (evita una dependencia circular con `ecs_service`).

### 11.4 `envs/dev/` (cómo se ensamblan)

**Variables** (`variables.tf`; valores de `terraform.tfvars` cuando difieren):

| Grupo | Variable (por defecto) |
|---|---|
| General | `project` (`campus-locator`), `env` (`dev`), `region` (`us-east-1`), `vpc_cidr` (`10.20.0.0/16`), `enable_nat_gateway` (`false`) |
| Interruptor | **`encendido`** (`true`): con `false`, backend y embedding quedan en 0 tareas (ver 11.5) |
| Cómputo | `backend_desired_count` (1), `embedding_desired_count` (1), `backend_cpu` (512), `backend_memory` (1024), `embedding_cpu` (2048), `embedding_memory` (4096), `image_tag` (`latest`), `embedding_model_name` (`dinov2_vitb14`), `log_retention_days` (7) |
| Datos | `db_instance_class` (`db.t4g.micro`), `db_multi_az` (`false`), `db_backup_retention_days` (7), `db_deletion_protection` (`false`), `create_scans_bucket` (`true`), `scans_expire_days` (1) |
| Borde | `certificate_arn` (`null`; fase 4) |
| Presupuesto | `monthly_budget_usd` (40), `budget_alert_email` (`""` = no crear el presupuesto; está comentada en `terraform.tfvars`) |

**Cableado (lo que `main.tf` decide):**
- Nombre base `campus-locator-<env>`; espacio DNS interno `campus.internal`; puertos **8000** (backend) y **8001** (embedding).
- **Subredes de las tareas:** públicas si `enable_nat_gateway = false` (con `assign_public_ip = true`, necesario para tirar imágenes de ECR sin NAT) y privadas si hay NAT. Los SG siguen cerrados: nada llega a las tareas salvo lo de abajo.
- `ecr` con `force_delete = true`, `storage` con `force_destroy = true` y `secrets` con `recovery_window_in_days = 0` **solo en dev** (para poder destruir y recrear).
- **Backend:** 512 CPU / 1024 MB, entrada solo desde el SG del ALB, registrado en el target group. Imagen `<url ECR backend>:<image_tag>`.
- **Embedding:** 2048 CPU / 4096 MB (modelo `dinov2_vitb14`), entrada solo desde el SG del backend, registrado en Cloud Map (`enable_service_discovery = true`; nombre `embedding.campus.internal`), **sin** rol de tarea con permisos. Imagen `<url ECR embedding>:<image_tag>`.
- **Base de datos:** una regla de entrada TCP `backend → puerto de RDS` (`aws_vpc_security_group_ingress_rule.db_from_backend`).
- **Permisos del rol de tarea del backend** (`data.aws_iam_policy_document.backend_task`): `s3:GetObject/PutObject/DeleteObject` sobre los objetos de los buckets, `s3:ListBucket` sobre los buckets, y `secretsmanager:GetSecretValue` sobre el secreto del JWT y el de la base. Nada más (los logs los escribe el rol de ejecución).
- **Presupuesto:** `aws_budgets_budget` mensual con avisos al 80 % (real) y 100 % (previsto) por correo, solo si `budget_alert_email != ""`.

**Variables de entorno que recibe el backend** (coinciden con 4.1, con estos detalles del código):

| Variable | Valor en dev |
|---|---|
| `APP_ENV`, `AWS_REGION` | `var.env`, `var.region` |
| `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME` | salidas del módulo `database` (puerto como texto) |
| `DATABASE_SECRET_ARN` | ARN del secreto que administra RDS. ⚠ Formato JSON esperado de ese secreto: usuario y contraseña (el backend debe leerlos con el SDK; confirmarlo al escribir el cliente) |
| `S3_BUCKET_DATASET`, `S3_BUCKET_SCANS` | nombres de los buckets; `S3_BUCKET_SCANS` llega **vacío** si `create_scans_bucket = false` |
| `EMBEDDING_SERVICE_URL` | `http://embedding.campus.internal:8001` |
| `JWT_SECRET_ARN` | ARN del secreto del JWT |

**Variables de entorno que recibe el embedding:** `APP_ENV`, `MODEL_NAME` (`dinov2_vitb14`) y `PORT` (`8001`).

**Salidas de `envs/dev`:** `api_base_url` (`http(s)://<dns del ALB>`; **es HTTP mientras no haya certificado**, ⚠ 12.5), `ecr_repository_urls`, `ecs_cluster_name`, `dataset_bucket`, `scans_bucket`, `database_host`, `database_secret_arn`.

**`backend.tf`:** state en S3, clave `envs/dev/terraform.tfstate`, región `us-east-1`, cifrado y `use_lockfile`. El bucket vale `4uproject-eafit-tfstate`: **hay que reemplazarlo** por el que imprime `bootstrap/` antes del primer `init`.

### 11.5 Interruptor de apagado

| Pieza | Detalle |
|---|---|
| Variable | `encendido` en `envs/dev` (por defecto `true`). En `main.tf`: `desired_count = var.encendido ? var.<servicio>_desired_count : 0` para backend y embedding |
| Apagar | `terraform apply -var encendido=false` o `scripts/dev-apagar.sh` (con `--con-bd` detiene también RDS) |
| Encender | `scripts/dev-encender.sh` (arranca RDS si estaba detenida, espera a que esté disponible y aplica `encendido=true`; imprime `api_base_url`) o `terraform apply -var encendido=true` |
| Qué deja de cobrar | Las tareas de Fargate (la mayor parte del costo) y sus IPv4 públicas. Con `--con-bd`, también el cómputo de RDS (queda solo el disco) |
| Qué **sigue** cobrando | El **ALB** (~17–22 USD/mes y sus IPv4), RDS si no se detuvo, Secrets Manager, S3, ECR y el disco de RDS |
| Cuidados | (1) RDS detenida **se reinicia sola a los 7 días**: si pasa más tiempo sin usarse, volver a detenerla. (2) No usar `aws ecs update-service --desired-count` para apagar: Terraform lo revertiría en el siguiente `apply`. (3) Al encender, el embedding tarda en cargar el modelo y el servicio puede reportar no sano unos minutos (`health_check_grace_seconds` solo cubre al backend, 60 s). (4) Los scripts suponen el identificador de RDS `campus-locator-dev-db` y credenciales de AWS CLI activas. ⚠ Sin probar; `bash -n` solo comprobó la sintaxis |
| Fuera de alcance | Apagar o destruir el ALB entre sesiones (ahorraría ~20 USD/mes más): requeriría hacer opcional el módulo `alb` y el `load_balancer` del backend; no está hecho |

### 11.6 Qué les pide esta infra a las otras carpetas (todavía no existe nada de esto)

- `BACKEND_FASTAPI/`: `Dockerfile`, `GET /health` → 200 sin autenticación, escuchar en `0.0.0.0:8000`, leer las variables de 11.4, y migraciones con **Alembic** (incluida `CREATE EXTENSION IF NOT EXISTS vector;`, ver 12.1).
- `SERVICE_EMBEDDING/`: `Dockerfile` con los pesos del modelo **dentro de la imagen**, `GET /health` → 200 solo con el modelo cargado, puerto 8001.
- `FRONTED_KOTLIN/`: leer `api_base_url` en `ApiConfig.kt` / `BuildConfig` (ver 4.3). Mientras la URL sea HTTP, Android la bloquea (⚠ 12.5).
- Arquitectura de las imágenes: `ecs_service` usa `X86_64` por defecto; la imagen que construya CI debe coincidir (o pasar `cpu_architecture = "ARM64"`).

---

## 12. Pendiente, riesgos y cosas por confirmar

### 12.1 `pgvector` no se habilita solo
Terraform crea la base pero no ejecuta SQL (está en subredes privadas, sin acceso desde fuera). La extensión se crea
una vez con `CREATE EXTENSION IF NOT EXISTS vector;` desde dentro de la VPC (lo natural es la primera migración de
Alembic). La sección 4.1 decía que la infra "habilita" la extensión: en la práctica **la habilita el backend**.

### 12.2 Los servicios no arrancan hasta que existan imágenes
Los servicios apuntan a `<ecr>/backend:latest` y `<ecr>/embedding:latest`, que no existen tras el primer `apply`.
Las tareas fallarán y el disyuntor de despliegue reintentará hasta que alguien suba una imagen. Como el servicio
tiene `ignore_changes = [task_definition]`, **subir una imagen nueva `latest` no redespliega** por sí solo: CI
debe registrar una definición nueva y actualizar el servicio (sección 7). Para el primer arranque basta forzar un
despliegue (`aws ecs update-service --force-new-deployment`).

**Estado actual:** el primer `apply` se hizo con `-var "encendido=false"`, así que los servicios están en 0 tareas y no
hay bucle de fallos. Encender (`terraform apply -var "encendido=true"`) solo después de subir las imágenes.

### 12.3 Validación y primer apply (hecho el 2026-10-13)
`terraform fmt`, `validate`, `plan` y `apply` se ejecutaron en `envs/dev` (y `apply` en `bootstrap/`): **65 recursos
creados**. Errores hallados y corregidos por el camino:
1. `Invalid count argument` en `modules/ecs_service` (el `count` dependía de `namespace_id`, desconocido al planificar):
   se añadió `enable_service_discovery` (ver cuidados en 11.3). Antes de la corrección el plan contaba 64 recursos;
   con ella, 65.
2. `engine_version = "16.4"` no existía en RDS (12.4).
3. Antes, ya se había corregido a mano un error de tipos en `storage` (un condicional entre objetos distintos).

Siguen sin observarse en ejecución: las tareas ECS, `/health` por el ALB, la conexión a RDS y los scripts de apagado.
Cualquier cambio futuro en un `.tf` vuelve a pedir `fmt`, `validate` y `plan` antes del `apply`.

### 12.4 Versión de PostgreSQL (resuelto)
`16.4` no existía en RDS. Consulta del 2026-10-13
(`aws rds describe-db-engine-versions --engine postgres --engine-version 16 --query "DBEngineVersions[].EngineVersion"`,
hecha en `us-east-2`): 16.9, 16.10, 16.11, 16.12, 16.13, 16.14 y 16.15. Se fijó `engine_version = "16.15"` y el
`apply` la aceptó. AWS retira versiones menores con el tiempo: si un `apply` futuro la rechaza, repetir la consulta
con el mismo `--region` que la infraestructura. `pgvector` exige PostgreSQL 15.2 o superior en RDS.

### 12.5 ⚠ HTTPS (decisión 9.3)
Sin `certificate_arn` el ALB solo habla HTTP y la app Android (API 28+) lo bloquea: sirve para probar con `curl`,
no para el teléfono. La fase 4 necesita decidir dominio (Route 53 + ACM, recomendado) o CloudFront. El módulo `alb`
ya acepta `certificate_arn`; falta `dns_cert` (registro DNS, validación del certificado y alias al ALB).

### 12.6 ⚠ Costo de dev (uso universitario: 1–2 clientes, encendido solo en desarrollo y exposición)
Estimaciones **de memoria, no consultadas en la lista de precios** (us-east-1): verificar con la calculadora de AWS.

| Escenario (embedding 2 vCPU / 4 GB, `dinov2_vitb14`) | USD/mes aprox. |
|---|---|
| Encendido 24/7 | ~140 (embedding ~72, backend ~18, ALB ~20, RDS ~14, IPv4 públicas ~15) |
| `encendido=false` salvo ~80 h/mes de uso, ALB y RDS siempre activos | ~40–45 (ALB e IPv4 del ALB ~27, RDS ~14, Fargate ~10) |
| Igual y RDS detenida fuera de uso (`--con-bd`) | ~30–35 |
| Alternativa no implementada: una sola instancia EC2 con Docker (backend + embedding + Postgres/`pgvector`), apagada fuera de uso, con IP elástica | ~10–15 |

- `monthly_budget_usd` baja a **40** (solo se crea con `budget_alert_email`). Si el apagado se olvida, la alarma al 80 %
  avisa; **el interruptor no es automático**: alguien debe ejecutarlo.
- La mayor partida fija que queda al apagar es el **ALB** (11.5, "Fuera de alcance"). Hacerlo opcional ahorraría ~20 USD/mes.
- 4 GB para `dinov2_vitb14` en CPU es un punto medio razonable, no una medición: probar con las 5 fotos de `/localize`
  y subir a 8 GB (`embedding_memory = 8192`) si hay falta de memoria. Con 2 vCPU Fargate acepta de 4 a 16 GB.
- Revisar créditos de la universidad o de la cuenta de AWS (AWS Academy, GitHub Student Pack, créditos de cuentas nuevas):
  es la decisión 9.1 y podría cubrir todo el costo.

### 12.7 Seguridad: matices frente a la sección 5
- El embedding "sin acceso a internet" (4.2) **no se cumple en dev**: la salida está abierta porque las tareas están
  en subredes públicas y deben llegar a ECR. En prod: subredes privadas + NAT o endpoints de VPC (ECR, S3, Logs,
  Secrets Manager) y salida restringida.
- El valor del secreto JWT **queda en el state** (lo genera `random_password`); el bucket del state está cifrado,
  versionado y restringido, pero hay que tratarlo como sensible. La contraseña de RDS **no** pasa por el state.
- El rol `github-ci` tiene `PowerUserAccess` + `IAMFullAccess` y lo puede asumir **cualquier rama** del repositorio
  (`repo:<owner/repo>:*`). Antes de usar CI en `prod`, limitarlo por rama/entorno (`ref:refs/heads/main`,
  `environment:prod`) y reducir permisos.
- Los buckets no tienen versionado (solo el del state): borrar un objeto del dataset es irreversible (ver decisión 9.10).
- ALB y RDS sin `deletion_protection` en dev (a propósito); en `prod` deben activarse (`alb.deletion_protection`,
  `database.deletion_protection`).

### 12.8 Desviación del plan: `modules/iam_cicd`
La sección 3 preveía un módulo `iam_cicd`. No se creó: el proveedor OIDC y el rol de GitHub viven en `bootstrap/`
(se necesitan antes de que exista cualquier ambiente). Si se quiere permisos distintos por ambiente (p. ej. un rol
de solo despliegue de imágenes), ahí sí cabe el módulo.

### 12.9 Fases por hacer
| Fase | Qué falta | Notas de diseño |
|---|---|---|
| 4 | `modules/dns_cert` | Zona/registro en Route 53, certificado ACM validado por DNS, alias al ALB; pasar `certificate_arn` a `alb`. Salida `api_base_url` ya cambia a `https` sola |
| 5 | `.github/workflows/` (5 archivos de la sección 7) | Rol: salida `github_ci_role_arn` de `bootstrap/`. Necesita `Dockerfile` y `/health` funcionales; despliegue = registrar definición de tarea con el SHA del commit y actualizar el servicio |
| 6 | `modules/observability` | Los log groups ya existen (`/ecs/<name>-<servicio>`). Faltan alarmas (5xx del ALB, CPU/memoria, espacio de RDS, tareas caídas), SNS al correo y dashboard |
| 7 | `envs/prod/` | Misma forma que `dev`: réplicas 2/2, RDS Multi-AZ y `deletion_protection = true`, retención de logs 30–90 días, `enable_nat_gateway` o endpoints, sin `force_delete`/`force_destroy`, `recovery_window_in_days` de 7 a 30, ALB con `deletion_protection`. `backend.tf` con clave `envs/prod/terraform.tfstate`. `desired_count` de `prod` lo gobierna CI tras el primer despliegue |
| 8 | GPU / lotes (opcional) | Solo si medir la indexación de 200 fotos en CPU resulta lenta (decisión 9.4) |

### 12.10 Otras decisiones que el código dejó sin resolver
- **Dominio** (9.3) y **privacidad de escaneos** (9.6: hoy el bucket existe y expira a 1 día; `scans_expire_days` no admite menos de un día en S3).
- **Subida directa a S3 con URL prefirmada** (9.9): hoy no hay CORS, ni permisos, ni nada de eso en `storage`; añadirlo si se adopta.
- **Moderación y respaldo** (9.10): sin versionado ni copias del dataset; quién ejecuta `apply` en `prod`.
- **Una sola zona de NAT / red:** si en `prod` se usa NAT, evaluar uno por zona.
- **¿Hace falta `envs/prod`?** Con 1–2 clientes y encendido solo en desarrollo y exposición, **probablemente no**: un
  único ambiente (`dev`) basta y la fase 7 y las diferencias de la sección 6 (Multi-AZ, réplicas 2/2, NAT) solo se
  justifican si el proyecto sigue más allá de la universidad. Confirmarlo y, si se descarta, tacharlo de 12.9.
- **Apagado automático:** hoy el interruptor es manual. Programar el apagado (EventBridge Scheduler + una acción de ECS)
  evitaría cobros por olvido; no está hecho.

### 12.11 Región
La AWS CLI local está en `us-east-2`, pero el código usa `us-east-1` (variable `region` por defecto en `bootstrap/` y
`envs/dev/`, y `backend.tf`). Todo lo creado el 2026-10-13 (state, VPC, RDS, ALB, ECR, ECS) está en `us-east-1`. Al
comprobar cosas con la CLI, pasar `--region us-east-1`. Si se prefiere otra región hay que cambiarla en las variables
y en `backend.tf` y recrear la infraestructura (decisión 9.2).

### 12.12 Proyecto dentro de OneDrive
El repositorio está en una carpeta de OneDrive (`...\OneDrive\Documentos\...\4U_project`). Igual que con Google Drive
(sección 1), `.terraform/` pesa cientos de MB y OneDrive puede bloquear o sincronizar archivos temporales. La primera
ejecución funcionó; si aparecen errores de permisos, mover el proyecto a una carpeta local (por ejemplo `C:\dev`).
`bootstrap/terraform.tfstate` (state local, ignorado por Git) debe conservarse aparte: si se pierde, el bucket del
state y el rol de GitHub quedan huérfanos.

### 12.13 Siguientes pasos inmediatos
1. Crear los `Dockerfile` de `BACKEND_FASTAPI/` y `SERVICE_EMBEDDING/` según 4.1, 4.2 y 11.6 (puertos 8000 y 8001,
   `GET /health`, pesos del modelo dentro de la imagen, arquitectura `X86_64`).
2. Construir y subir las imágenes a los repositorios de ECR (`ecr_repository_urls` en las salidas de `envs/dev`).
3. Encender: `terraform apply -var "encendido=true"` y forzar el primer despliegue si hace falta (12.2).
4. Comprobar `GET /health` por la URL de `api_base_url` (HTTP, solo con `curl`).
5. Habilitar `pgvector` con la primera migración de Alembic (12.1).
6. Resolver HTTPS (fase 4, 12.5) antes de probar con la app en un teléfono.

**Costo con todo apagado:** siguen cobrando el ALB (~20 USD/mes) y RDS (~14 USD/mes, estimaciones de 12.6). Si el
proyecto se pausa varios días, detener RDS o ejecutar `terraform destroy` en `envs/dev`.