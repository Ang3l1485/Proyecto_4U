# PLAN — Infraestructura (`INFRASTRUCTURA_TERRAFORM`)

Qué se construye y en qué orden. **Cómo** funciona cada pieza está en [`ARCHITECTURE.md`](./ARCHITECTURE.md);
**por qué y cuándo** cambió algo, en [`CHANGELOG.md`](./CHANGELOG.md); **cómo se comprueba** cada lote, en
[`validation/`](./validation/).

Alineado con `ARCHITECTURE.md` **v0.5.0**.

---

## 1. Cómo usar este plan

- No hay fechas: el orden lo dan las fases y las dependencias.
- **Identificadores:** `INF-<fase>.<n>` (n = orden del lote dentro de su fase). La fase es siempre de un dígito.
- **§3 es la única tabla de estado de esta carpeta.** Al cerrar un lote solo se edita su fila en §3.
- **Dos tipos de dependencia** (§2.2):
  - *Para construir:* lo que debe existir para escribir el código del lote.
  - *Para validar:* lo que debe estar **Hecho**, en esta u otras carpetas, para ejecutar su validación en `dev`. Son las
    precondiciones que el validador comprueba primero; si faltan, termina con código 2 y el lote queda `Bloqueado`.
- **Cerrar un lote:**
  1. Cumplir todos sus criterios (C1, C2…, en §2.3).
  2. Ejecutar su validación (`docs/validation/validation-<fase>-<n>.md`, script `project/src/ops/validate<fase><n>.py`)
     en `dev`, con código de salida 0.
  3. Dejar en el PR la evidencia de las comprobaciones marcadas como manuales.
  4. Actualizar la fila del lote en §3 (estado, commit y fecha de la última ejecución).
  5. Si el lote cambió una interfaz, antes se actualiza `ARCHITECTURE.md` §5 (sube la versión) y se añade la entrada en
     `CHANGELOG.md`.
- El contrato común de los validadores está en `ARCHITECTURE.md` §5.11; el orden global entre carpetas, en el
  `README.md` raíz.
- Prefijos de otras carpetas: `BE-` (backend), `EMB-` (embeddings), `FE-` (app). Su estado está en el §3 de su
  `PLAN.md`.
- Las historias de usuario tienen un **catálogo único** en `FRONTEND_KOTLIN/docs/PLAN.md` §5 (todas son propuestas).

---

## 2. Fases y lotes

### 2.1 Fases (comunes a las cuatro carpetas)

| Fase | Objetivo | Se considera lograda cuando… |
|---|---|---|
| 0 — Cimientos | Cuenta, estado remoto, CI y control de gasto. En la app, además, el prototipo ya construido con datos locales | Un PR de Terraform produce un `plan` automático y hay presupuesto con avisos |
| 1 — Plataforma mínima en línea | La app llega por HTTPS a un backend real con base de datos | `GET /v1/health` responde desde la URL pública y el admin inicia sesión con un JWT real |
| 2 — Dataset | Un recorrido grabado en la app termina indexado | Las fotos de un video subido quedan `procesada` con su vector en pgvector |
| 3 — Ubicarse | Una vuelta de 360° devuelve una posición útil | `POST /v1/localize` responde con posición y confianza en un punto conocido del campus |
| 4 — Administración completa | El admin gestiona dataset, lugares y alertas contra el backend | Las vistas de admin dejan de usar datos locales o *stubs* |
| 5 — Navegación guiada (diferida) | Guía por voz hasta un destino, con corrección visual | — |
| 6 — Endurecimiento y producción (diferida) | Entorno `prod` confiable | — |

### 2.2 Lotes por fase

| Lote | Nombre | Para construir | Para validar | Validación |
|---|---|---|---|---|
| INF-0.1 | Bootstrap de la cuenta | — | Repositorio de GitHub creado | [`validation-0-1`](./validation/validation-0-1.md) |
| INF-0.2 | Esqueleto de `envs/dev` y CI de Terraform | INF-0.1 | INF-0.1 | [`validation-0-2`](./validation/validation-0-2.md) |
| INF-1.1 | Red y grupos de seguridad | INF-0.2 | INF-0.2 | [`validation-1-1`](./validation/validation-1-1.md) |
| INF-1.2 | Datos y secretos | INF-1.1 | INF-1.1 | [`validation-1-2`](./validation/validation-1-2.md) |
| INF-1.3 | Cómputo (ECR, ECS, Cloud Map, IAM de tareas) | INF-1.2 | INF-1.2 | [`validation-1-3`](./validation/validation-1-3.md) |
| INF-1.4 | Borde HTTPS (API Gateway) | INF-1.3 | INF-1.3 | [`validation-1-4`](./validation/validation-1-4.md) |
| INF-2.1 | Escalado del `worker` y horario de `dev` | INF-1.3 | INF-1.3 | [`validation-2-1`](./validation/validation-2-1.md) |
| INF-3.1 | Observabilidad y alarmas | INF-1.4 | INF-1.4, INF-2.1 | [`validation-3-1`](./validation/validation-3-1.md) |
| INF-6.1 | Entorno `prod` y optimizaciones (diferido) | Fases 1–4 cerradas | — | — |

Ningún lote de infraestructura necesita código del backend, de embeddings o de la app para validarse: donde hace
falta un contenedor se usa una **imagen de prueba** que responde `GET /v1/health` y `GET /health/ready`
(ARCHITECTURE §5.11).

### 2.3 Detalle de cada lote

#### INF-0.1 — Bootstrap de la cuenta
- **Objetivo:** que exista lo mínimo para trabajar con estado remoto y CI sin llaves de larga duración.
- **Entregables:** `project/bootstrap/` (bucket de estado, proveedor OIDC, roles `campus-locator-gha-terraform-plan`,
  `campus-locator-gha-terraform` y `campus-locator-gha-deploy`, *permissions boundary* `campus-locator-limite-roles`,
  presupuesto `campus-locator-mensual`); higiene manual de la cuenta (ARCHITECTURE §3.1); variables de GitHub
  `AWS_REGION`, `AWS_ROL_TERRAFORM_PLAN_ARN`, `AWS_ROL_TERRAFORM_ARN`, `AWS_ROL_DEPLOY_ARN` y entorno `dev` de GitHub
  con aprobación manual y despliegue solo desde `main` (ARCHITECTURE §3.9), ambos con `bootstrap/configurar_github.py`;
  `project/pyproject.toml`, `project/src/ops/comun.py` y `project/.gitignore`, que necesita el validador de este lote.
- **Requiere decidir antes:** `github_repo`, `correo_alertas` y, si el repositorio usa el `sub` inmutable de OIDC,
  `github_ids` (ARCHITECTURE §5.3). Decididos el 2026-10-23.
- **Criterios de cierre:**
  - C1. El estado de `bootstrap` está en `bootstrap/terraform.tfstate` del bucket de estado, versionado y cifrado.
  - C2. Un workflow de prueba asume `gha-terraform-plan` desde un PR y ejecuta `aws sts get-caller-identity`.
  - C3. El entorno `dev` de GitHub exige aprobación manual y solo admite la rama `main`, y `gha-terraform` solo confía
    en `environment:dev` (que lo asume de verdad lo prueba INF-0.2 C2 al aplicar).
  - C4. Un PR **no** puede asumir `gha-terraform` ni `gha-deploy`: sin entorno lo rechaza AWS y declarando
    `environment: dev` lo rechaza GitHub.
  - C5. El presupuesto existe con los tres avisos de §5.10 y `correo_alertas` como suscriptor `EMAIL`.
- **Historias:** HU-20, HU-21.

#### INF-0.2 — Esqueleto de `envs/dev` y CI de Terraform
- **Objetivo:** que todo cambio de infraestructura entre por PR con `plan` revisable.
- **Entregables:** `project/envs/dev/` (backend S3 con `use_lockfile`, proveedor con `default_tags` y
  `allowed_account_ids`, `.terraform.lock.hcl` versionado), `data "aws_caller_identity"` con el output `cuenta_id`
  (ARCHITECTURE §5.2) y `data "aws_default_tags"`, módulos vacíos en `project/modules/`, `project/.tflint.hcl`,
  `.github/workflows/infra.yml` (el `apply` usa el entorno `dev` de INF-0.1) y `src/ops/validate02.py`. `.gitignore`,
  `pyproject.toml` y `src/ops/comun.py` ya existen desde INF-0.1: aquí no cambian (`envs/dev/.gitignore` complementa
  el de `project/`).
- **Criterios de cierre:**
  - C1. Un PR con un cambio trivial publica el `plan` como comentario.
  - C2. Al fusionarlo, el `apply` espera la aprobación y termina sin errores.
  - C3. Dos `plan` simultáneos no corrompen el estado: el segundo espera el bloqueo.
  - C4. El proveedor rechaza credenciales de otra cuenta (`allowed_account_ids`) y declara las `default_tags` de §5.1
    (cada lote posterior comprueba las etiquetas de los recursos que crea).
- **Historias:** HU-20.

#### INF-1.1 — Red y grupos de seguridad
- **Objetivo:** la red de ARCHITECTURE §3.2 y los grupos de §5.7.
- **Entregables:** módulo `red` (§3.2, §5.1, §5.7; entradas y salidas en §5.12); en `envs/dev`, `local.prefijo`, las
  variables `cidr_vpc`, `az_computo` y `az_secundaria` (§5.3) y los outputs `subredes_tareas` y `sg_migrate` (§5.2);
  `src/ops/validate11.py`.
- **Criterios de cierre:**
  - C1. `plan` vacío tras el `apply`.
  - C2. VPC, subredes, rutas y endpoint de S3 coinciden con §3.2 y §5.1, nombres y etiquetas incluidos.
  - C3. Las reglas de los cinco grupos de seguridad coinciden con §5.7 y el grupo `default` de la VPC no tiene reglas.
  - C4. Ninguna regla entrante tiene origen `0.0.0.0/0` ni `::/0`.
  - C5. Los outputs `subredes_tareas` y `sg_migrate` existen y apuntan a `publica-a` y a `campus-locator-dev-api`.
- **Historias:** habilita HU-01, HU-10, HU-13.

#### INF-1.2 — Datos y secretos
- **Objetivo:** RDS, bucket del dataset, colas y secretos listos para que el backend migre y la app suba fotos.
- **Entregables:** módulos `datos` y `secretos` según §3.5, §5.4, §5.5 y §5.6.
- **Criterios de cierre:**
  - C1. Subir un `.jpg` a `dataset/` deja un mensaje en `ingesta` con la clave correcta.
  - C2. Un `.png`, o un `.jpg` fuera de `dataset/`, no deja mensaje.
  - C3. RDS no es accesible desde internet (sin IP pública, sin regla entrante abierta) y exige TLS.
  - C4. La versión del motor es 17.1 o superior (la que trae pgvector 0.8 en RDS).
  - C5. Los tres secretos existen con las claves de §5.4; bucket y colas tienen los atributos de §5.5 y §5.6.
- **Historias:** habilita HU-13, HU-14, HU-23.

#### INF-1.3 — Cómputo
- **Objetivo:** clúster, repositorios, roles y servicios listos para recibir imágenes.
- **Entregables:** módulo `computo` (§3.4, §5.1, §5.7, §5.8; sus roles con `permissions_boundary` = output
  `limite_roles_arn` de `bootstrap`), incluida la tarea de validación; imagen de prueba
  `bootstrap` (`project/pruebas/imagen-prueba/`, §5.11) publicada en los dos repositorios; outputs de §5.2.
- **Criterios de cierre:**
  - C1. Con la imagen de prueba, el servicio `api` queda estable y se registra en Cloud Map con SRV.
  - C2. `embedding.campus-locator.local` resuelve desde la tarea de validación.
  - C3. Los roles de tarea no tienen más permisos que §5.8 (simulación de políticas de IAM).
  - C4. Existen los outputs de §5.2 que corresponden a INF-1.1–INF-1.3 (todos salvo `api_base_url` y `sns_alertas_arn`)
    y apuntan a recursos reales.
  - C5. Desde la tarea de validación (§5.11), la base acepta conexión con TLS y
    `CREATE EXTENSION IF NOT EXISTS vector` funciona.
- **Historias:** HU-20.

#### INF-1.4 — Borde HTTPS
- **Objetivo:** URL pública HTTPS que llegue a `api`.
- **Entregables:** módulo `borde`; output `api_base_url`.
- **Criterios de cierre:**
  - C1. `GET {api_base_url}/v1/health` devuelve 200 desde fuera de AWS (imagen de prueba o la de BE-1.1).
  - C2. Más de 2 req/s sostenidas a `POST /v1/auth/login` reciben 429; la ruta general no.
  - C3. Los *access logs* aparecen en `/campus-locator/dev/apigw`.
- **Historias:** HU-09, HU-10.

#### INF-2.1 — Escalado del `worker` y horario de `dev`
- **Objetivo:** pagar `embedding` y `worker` solo cuando se usan.
- **Entregables:** acciones programadas y política por pasos (§3.4, §5.10).
- **Criterios de cierre:**
  - C1. Las acciones programadas existen con la zona y las horas de §5.3; a la hora de apagar `embedding` queda en 0 y a
    la de encender vuelve a 1.
  - C2. Con mensajes de prueba en `ingesta`, `worker` sube a 1 y vuelve a 0 a los ~15 min de vaciarse la cola.
  - C3. Fuera del horario, `worker` no arranca aunque haya mensajes.
- **Historias:** HU-21.

#### INF-3.1 — Observabilidad y alarmas
- **Objetivo:** enterarse de los fallos sin mirar la consola.
- **Entregables:** módulo `observabilidad` (topic SNS, suscripción, alarmas de §5.10, regla de EventBridge de §3.8) y
  output `sns_alertas_arn`.
- **Criterios de cierre:**
  - C1. Existen todas las alarmas de §5.10 apuntando al topic, con los nombres de §5.1, y la suscripción por correo
    está confirmada.
  - C2. Un mensaje en una DLQ dispara su alarma y llega el correo.
  - C3. Detener una tarea por error dispara la regla de EventBridge y llega el correo.
- **Historias:** HU-22.

#### INF-6.1 — Entorno `prod` y optimizaciones (diferido)
- **Alcance previsto:** `envs/prod`, RDS Multi-AZ, *interface endpoints* o NAT con tareas en subredes privadas,
  dominio propio con certificado de ACM, WAF en la API, Graviton (ARM64) si las imágenes lo permiten, rotación de la
  contraseña de la base, ejecución de los validadores en CI.
- **Requiere decidir antes:** presupuesto de `prod`, dominio, decisión abierta 1 del frontend (proveedor de teselas).
- **Historias:** HU-20, HU-21, HU-22.

---

## 3. Estado de los lotes

> **Única tabla de estado.** Valores: `Pendiente`, `En curso`, `Bloqueado` (una precondición de validación no se
> cumple), `Hecho`, `Diferido`. «Última validación» = commit corto y fecha de la última ejecución con código 0 en `dev`.

| Lote | Fase | Estado | Validación | Última validación | Versión de ARCHITECTURE al cerrar | Nota |
|---|---|---|---|---|---|---|
| INF-0.1 | 0 | Hecho | [0-1](./validation/validation-0-1.md) | `b20a62f` 2026-10-24 | 0.3.0 | `sub` inmutable de OIDC (`github_ids`); proveedor OIDC importado de un intento anterior |
| INF-0.2 | 0 | Hecho | [0-2](./validation/validation-0-2.md) | `c677aeb` 2026-10-24 | 0.4.0 | Primer `apply` de `envs/dev` hecho por `infra.yml`; C3b toma el bloqueo él mismo (`terraform console` ya no lo toma desde Terraform 1.15) |
| INF-1.1 | 1 | En curso | [1-1](./validation/validation-1-1.md) | — | — | Código escrito; faltan el `apply` desde `main` y `validate11.py` en `dev` |
| INF-1.2 | 1 | Pendiente | [1-2](./validation/validation-1-2.md) | — | — | Antes: el bucket `campus-locator-dev-dataset-648617469176` ya existe (intento anterior, ARCHITECTURE R11) |
| INF-1.3 | 1 | Pendiente | [1-3](./validation/validation-1-3.md) | — | — | |
| INF-1.4 | 1 | Pendiente | [1-4](./validation/validation-1-4.md) | — | — | |
| INF-2.1 | 2 | Pendiente | [2-1](./validation/validation-2-1.md) | — | — | |
| INF-3.1 | 3 | Pendiente | [3-1](./validation/validation-3-1.md) | — | — | |
| INF-6.1 | 6 | Diferido | — | — | — | |

---

## 4. Matriz de trazabilidad

Historias que cada lote **entrega** (●) o **habilita** (○, la historia la cierra otra carpeta pero no es posible sin
este lote). Solo se listan las historias que tocan esta carpeta.

| Historia | 0.1 | 0.2 | 1.1 | 1.2 | 1.3 | 1.4 | 2.1 | 3.1 | 6.1 |
|---|---|---|---|---|---|---|---|---|---|
| HU-01 Ubicarme con una vuelta | | | ○ | ○ | ○ | ○ | | | |
| HU-09 Saber si hay conexión | | | | | | ○ | | | |
| HU-10 Iniciar sesión como admin | | | ○ | ○ | ○ | ○ | | | |
| HU-13 Recolectar fotos | | | ○ | ○ | | | | | |
| HU-14 Subir un recorrido | | | | ○ | ○ | | ○ | | |
| HU-20 Desplegar automáticamente | ● | ● | | | ● | | | | ● |
| HU-21 Gasto bajo 100 USD/mes | ● | | | | | | ● | | ● |
| HU-22 Diagnosticar fallos | | | | | | | | ● | ● |
| HU-23 Privacidad de quien se ubica | | | | ○ | | | | | |

(Columnas = `INF-0.1` … `INF-6.1`.)
