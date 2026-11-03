# Validación 2-2 — BE-2.2 Worker de ingesta

| Campo | Valor |
|---|---|
| Lote | `BE-2.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate22.py` |
| Entornos | `dev` (necesita S3, SQS y `embedding`, que no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |
| Hora límite para empezar | **21:00 de Bogotá** (UTC−5): dura 35–60 min y `embedding` se apaga solo a las 22:00 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-2.2: `EmbeddingDev`, `eventos_worker`…). Cómo funciona el `worker`:
`ARCHITECTURE.md` §4.6.

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, permisos u hora), sin
crear nada. P6 es la única que cambia algo (enciende `embedding`) y va la última.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | `BE-2.1` desplegado: API, login de admin y recolección | `GET /v1/health` → `200`; `POST /v1/auth/login` (admin, §5) → `200` con rol `admin` (un `401` es código 3); `POST /v1/collect/videos/<uuid nuevo>/images` con un elemento válido → `404 NO_ENCONTRADO` |
| P3 | `EMB-2.1` en «Hecho» | La fila `EMB-2.1` de `SERVICE_EMBEDDING/docs/PLAN.md` §3 dice `Hecho` |
| P4 | `INF-2.1` aplicado y dentro de horario | `application-autoscaling describe-scalable-targets` con los objetivos de `embedding` y `worker`, `describe-scaling-policies` de `worker` con `campus-locator-dev-worker-cola` y `describe-scheduled-actions` de `embedding` con `campus-locator-dev-embedding-apagar-noche` (si falta algo: código 2). Hora de Bogotá antes de las 21:00 (si no: código 3) |
| P5 | Recursos para inspeccionar, y `worker` con la imagen de BE-2.2 | Outputs `sqs_ingesta_url`, `sqs_ingesta_dlq_url`, `bucket_dataset`, `subredes_tareas` y `sg_migrate`; `comprobar_bucket` (como P4 de BE-2.1), `sqs get-queue-attributes` de `ingesta`, `describe-task-definition` de `campus-locator-dev-validacion`, y la última revisión de `campus-locator-dev-worker` con **la misma imagen** que el servicio `api` (`EntornoBackend.revision`; si no: código 2, «BE-2.2 sin desplegar del todo») |
| P6 | `embedding` encendido y visto por `api` | Si `embedding` tiene `desiredCount ≥ 1` y `/v1/health/ready` dice `"embedding": "ok"`: solo publica un latido (`EmbeddingEncendidos`), que aleja el apagado por inactividad. Si no: lo enciende con el contrato de infra §5.10 (§4) y espera a `"embedding": "ok"`. Anota cómo lo encontró **antes** de encender (la limpieza lo apaga aunque el encendido falle a medias). Si no queda listo: código 2 |

**Preparación** (tras las precondiciones; un fallo solo se avisa): si `GET /v1/admin/videos?q=validacion-` (todas las
páginas) tiene restos con `nombre` **y** `ref_cliente` `validacion-…`, lanza `limpiar-validacion` sin `--video`
(`comun.borrar_restos`). Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Crea el video `validacion-22-<AAAAMMDD-HHMMSS>` (6 fotos declaradas, coordenadas `1.0, -100.0`), registra y sube las fotos 1–3 (JPEG sintéticos de 1024×768, `comun.jpeg_sintetico`) y lee `GET /v1/admin/videos/{id}` cada 15 s | Fotos 1–3 en `procesada` antes de **20 min** (si `worker` estaba en 0, su subida tarda de 2 a 15 min, infra ADR-INF-15). Una foto en `error` es `falla` inmediata, con su motivo |
| C1b | SQL `SELECT imagen_id, version_vector, extract(epoch FROM creado_en) FROM embeddings WHERE imagen_id IN (<fotos 1–3>)` (tarea `campus-locator-dev-validacion`, `psql -tAc`) | Una fila por foto, con `version_vector = 'dinov2-vits14/pp-v1'`. Guarda `creado_en` para C4 y C5 |
| C1c | `s3 get-object` de `thumbs/{video_id}/{imagen_id}.jpg` de las fotos 1–3, decodificadas con Pillow | Existen, son JPEG y su lado mayor es ≤ 320 px (`MINIATURA_LADO_PX`) |
| C2 | Anota los mensajes de la DLQ de `ingesta` (visibles + en vuelo); registra la foto 4 y sube con su URL firmada el texto `validacion-no-es-jpeg` (`Content-Type: image/jpeg`); lee el detalle cada 15 s | Foto 4 en `error` antes de 20 min, con `error` no vacío (`no es un JPEG decodificable`), y la DLQ con el mismo número de mensajes |
| C4 | `s3 head-object` de la foto 1 (ETag y tamaño); `sqs send-message` a `ingesta` con el evento de §5.8 `{"Records": [{"eventName": "ObjectCreated:Put", "s3": {"bucket": {"name": "<bucket>"}, "object": {"key": "dataset/<video_id>/<foto 1>.jpg", "size": <bytes>, "eTag": "<ETag sin comillas>"}}}]}`; espera (hasta 5 min) en `/campus-locator/dev/worker` el evento `mensaje_descartado` con `motivo = duplicado` de esa foto (`comun.eventos_worker`); repite el SQL de C1b | El `worker` lo descartó como duplicado, la foto sigue con **un** vector y el mismo `creado_en`, y la DLQ no cambió |
| C5 | Envía a `ingesta` `{"tipo": "reprocesar_imagen", "version": 1, "imagen_id": "<foto 2>", "solicitado_por": "<id del admin>", "solicitado_en": "<ahora>"}`; espera (hasta 5 min) en el log del `worker` `imagen_procesada` con `origen = reprocesar` de esa foto; SQL `SELECT extract(epoch FROM e.creado_en), i.estado FROM embeddings e JOIN imagenes i …` | Una sola fila en `embeddings` para la foto 2, con `creado_en` posterior al de C1b (los dos son hora de la base: no depende del reloj local), y la foto en `procesada` |
| C3a | Exige ≥ 25 min antes de las 22:00 en Bogotá y `"embedding": "ok"`; anota las tareas de `worker`; `ecs update-service --service embedding --desired-count 0`; espera (hasta 5 min) `"embedding": "no_disponible"` en `/v1/health/ready` y 0 tareas de `embedding`; espera 45 s más (espera larga de 20 s + pausa del `worker` de 15 s + TTL del DNS de 10 s); registra y sube las fotos 5 y 6 con URLs nuevas; durante 6 min (2 × la visibilidad de 180 s) muestrea cada 30 s `ApproximateNumberOfMessages` y `…NotVisible` de `ingesta` | En cada muestra, ≥ 2 visibles y 0 en vuelo (el `worker` no recibe sin `embedding`); si `worker` tenía tareas al empezar, sigue con ≥ 1 al final (vivo y sin consumir); fotos 5 y 6 sin `procesada` |
| C3b | Enciende `embedding` con el contrato de infra §5.10 (poner `desiredCount = 1` sin más no basta: la alarma de inactividad lo devolvería a 0) y espera `"embedding": "ok"` | Fotos 5 y 6 en `procesada` antes de 20 min desde que `embedding` está listo, y la DLQ con el número anotado en C2 |

Orden de ejecución: C1, C2, C4, C5, C3 (C3 apaga `embedding` y va al final). C5 envía el mensaje directamente porque
`POST /v1/admin/images/{id}/reprocesar` llega con BE-4.1. Cada comprobación prepara lo que le falta si se ejecuta sola
con `--solo` (p. ej. `--solo C4` crea el video, sube la foto 1 y espera a que se procese). C4 y C5 no se fían de los
contadores de SQS (aproximados y con retraso): esperan el evento del `worker` en su log. El script nunca imprime URLs
prefirmadas, tokens ni contraseñas.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea el video `validacion-22-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 6 fotos: cinco JPEG sintéticos (semilla
distinta en cada ejecución) y un archivo que no es JPEG (foto 4). Los dos mensajes que inyecta en `ingesta` solo
nombran fotos de ese video y los consume el `worker`. Lanza 3 tareas de `campus-locator-dev-validacion` (SQL de C1b, C4
y C5) y 1 o 2 de `campus-locator-dev-worker` (`limpiar-validacion` al final, y al empezar si había restos).

**`embedding`** (infra §5.10 y §5.11; `comun.EmbeddingDev.encender`, el mismo contrato que `embedding.py encender` de
infra): 1) `RegisterScalableTarget` 0-1 de `embedding` y `worker`; 2) `PutMetricData` de `EmbeddingEncendidos` = 1 en
`campus-locator/dev`; 3) espera a que `GetMetricStatistics` la devuelva, un minuto más y que la alarma
`campus-locator-dev-embedding-inactivo` no esté en `ALARM` (hasta 5 min); 4) `UpdateService` de `embedding` a 1;
5) espera tarea `HEALTHY`, despliegue `COMPLETED` y esa tarea registrada en Cloud Map (`servicediscovery
list-instances` con su IP privada: el servicio de Cloud Map no tiene configuración de salud, ARCHITECTURE §5.11
«Trampa del arranque») (hasta 10 min desde el paso 1) y,
además, `"embedding": "ok"` en `/v1/health/ready` (hasta 2 min). Cuesta ~0,10 USD/h mientras está encendido.

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`, que deja también `embedding` como esté), en
este orden:
1. Deja `embedding` como lo encontró: si lo encendió el script (P6), lo apaga como `embedding.py apagar` (rango 0-0 y
   `desiredCount = 0` de `embedding` y `worker`; no espera a que paren); si estaba encendido y un fallo a mitad de C3
   lo dejó en 0, lo vuelve a encender con el contrato. Imprime `embedding apagado (lo encendió el validador)`,
   `embedding sigue encendido (como estaba)` o `embedding vuelto a encender (estaba encendido)`; si no lo consigue,
   `[LIMPIEZA] falló: … embedding NO quedó como estaba …` (entonces, paso 7 de §5).
2. Borra su video con `limpiar-validacion --video <id>` (tarea suelta con `campus-locator-dev-worker`, ARCHITECTURE
   §5.11; con `DELETE /v1/admin/videos/{id}` cuando BE-4.1 esté «Hecho»): filas (en cascada fotos y vectores) y
   objetos de `dataset/` y `thumbs/`.

Si el script se interrumpe (Ctrl+C, terminal cerrada), `embedding` puede quedar encendido hasta las 22:00 o hasta 45
min sin uso: paso 7 de §5. Los mensajes de sus fotos que queden en `ingesta` con `embedding` apagado esperan; cuando se
encienda, el `worker` los descarta (`video_no_existe`) si el video ya se borró.

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Además de lo de BE-2.1 (secreto `admin-inicial`, S3 del dataset, `ecs run-task`/`describe-*`, `iam:PassRole` de `worker` y `validacion`, `logs:GetLogEvents`), necesita `sqs:GetQueueAttributes` y `sqs:SendMessage` en `ingesta` y su DLQ, `s3:GetObject` en `thumbs/*`, `logs:FilterLogEvents` en `/campus-locator/dev/worker`, `application-autoscaling:Describe*` y `RegisterScalableTarget`, `cloudwatch:PutMetricData`, `GetMetricStatistics` y `DescribeAlarms`, `ecs:UpdateService`, `ListTasks` y `DescribeTasks`, y `servicediscovery:ListInstances` (con `campus-admin`, todo) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`. El
informe queda en `project/.validacion/BE-2.2-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe RUTA`. Durante C3
(~8 min), `/v1/localize` de `dev` respondería `503 EMBEDDING_NO_DISPONIBLE`. Recursos compartidos (los coordina el
maestro): mientras corre, nadie más enciende o apaga `embedding`, cambia `desiredCount` de `worker`, deja mensajes en
`ingesta` ni hace push a `main` con cambios en `BACKEND_FASTAPI/project/**` o `SERVICE_EMBEDDING/project/**`.

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo en la máquina, con el PostgreSQL del compose para las pruebas `base`:

```bash
cd BACKEND_FASTAPI/project
docker compose up -d --wait db
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `… files already formatted` y `… passed` sin fallos ni omitidas.

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>` (ya con
Pillow), ejecuta `migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker`. Esperado: el
workflow en verde.

3. Comprobar que `api` sirve ese commit (desde `BACKEND_FASTAPI/project`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}`.

4. Comprobar que la revisión de `worker` lleva la misma imagen que `api` (si no, P5 termina con 2):

```bash
export AWS_PROFILE=campus-admin
aws ecs describe-task-definition --task-definition campus-locator-dev-worker --query 'taskDefinition.containerDefinitions[0].image' --output text
aws ecs describe-task-definition --task-definition $(aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].taskDefinition' --output text) --query 'taskDefinition.containerDefinitions[0].image' --output text
```

Esperado: dos líneas iguales, `…/campus-locator/backend:<SHA del commit>`.

5. Mirar la hora y el estado de `embedding`, `worker` y la DLQ (solo lectura):

```bash
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_ingesta_dlq_url) --attribute-names ApproximateNumberOfMessages --output text
```

Esperado: una hora **antes de las 21:00**; `embedding 0 0` y `worker 0 0` (apagados: el script los enciende y al
final los apaga) o `embedding 1 1` (encendido: lo deja encendido); y el número de mensajes de la DLQ (el script solo
exige que no cambie).

**Ejecución.**

6. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate22.py --entorno dev
```

Esperado (35–60 min; el progreso del encendido sale por stderr): código 0, con `[PASA]` en P1–P6 y en C1a, C1b, C1c,
C2, C4, C5, C3a y C3b. P6 termina en `embedding encendido en N s · /v1/health/ready → "embedding": "ok"` (o
`embedding ya encendido (latido publicado) · …`); antes de C1, `[PREPARACION] sin restos validacion- de ejecuciones
anteriores`; C1a `video <id>: fotos 1–3 subidas y en procesada en N min`; C1b `un vector por foto con version_vector
= dinov2-vits14/pp-v1`; C1c `3 miniaturas JPEG (320×240, 320×240, 320×240), lado mayor ≤ 320 px`; C2 `foto 4 en
error ('no es un JPEG decodificable') · DLQ con N mensajes, como antes`; C4 `evento repetido consumido
(mensaje_descartado: duplicado) · 1 vector, creado_en sin cambios · DLQ igual`; C5 `vector regenerado (un solo
vector, creado_en posterior) · foto 2 procesada`; C3a `12 muestras en 6 min: ≥ 2 visibles y 0 en vuelo · worker con
1 tarea(s) · fotos 5 y 6 sin procesar`; C3b `embedding ok · fotos 5 y 6 procesadas N min después · DLQ con N, como
antes`; y al final `[LIMPIEZA] embedding apagado (lo encendió el validador) · videos de prueba borrados: {"videos": 1,
"objetos": 11}` (6 originales, uno de ellos el texto de la foto 4, y 5 miniaturas) o, si lo encontró encendido,
`[LIMPIEZA] embedding sigue encendido (como estaba) · …`. Con eso, el maestro pasa la fila BE-2.2 de PLAN §3 a
«Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

7. Solo si el script se interrumpió (o la limpieza dijo `embedding NO quedó como estaba`) y en el paso 5 `embedding`
estaba apagado: apagarlo con la herramienta de infra (infra §5.11) y comprobarlo:

```bash
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: código 0 y las líneas `embedding 0` y `worker 0`. Los restos del video los borra la preparación de la
siguiente ejecución.

En `local` no se ejecuta (S3 y SQS no se emulan): el script termina con 3 (`BE-2.2 solo admite el entorno: dev`). Lo
que sí se comprueba en `local` está en las pruebas del paso 1: el `worker` con PostgreSQL real y S3, SQS y embeddings
simulados (`tests/base/test_ingesta_base.py` cubre C1–C5; `tests/unit/test_worker.py`, la puerta de `embedding`) y el
validador contra un mundo falso con un `worker` simulado (`tests/ops/test_validate22.py`).
