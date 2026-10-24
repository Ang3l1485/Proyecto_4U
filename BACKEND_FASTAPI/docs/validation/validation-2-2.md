# Validación 2-2 — BE-2.2 Worker de ingesta

| Campo | Valor |
|---|---|
| Lote | `BE-2.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate22.py` |
| Entornos | `dev` (necesita S3 y SQS, que no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-2.1` en «Hecho»: login y recolección desplegados | `POST /v1/auth/login` (admin, ver §5) → `200`; `POST /v1/collect/videos/<uuid nuevo>/images` con un elemento válido → `404 NO_ENCONTRADO` |
| P3 | `EMB-2.1` en «Hecho»: embeddings listo y con la `version_vector` esperada | `SERVICE_EMBEDDING/docs/PLAN.md` §3 marca EMB-2.1 «Hecho»; `GET /v1/health/ready` → `"embedding": "ok"` |
| P4 | `INF-2.1` en «Hecho» y ejecución dentro del horario | `application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id service/campus-locator-dev/worker` (y `…/embedding`) devuelve acciones; hora `America/Bogota` entre 06:00 y 21:30 |
| P5 | Recursos para inspeccionar | Outputs `sqs_ingesta_url`, `sqs_ingesta_dlq_url`, `subredes_tareas` y `sg_migrate`; `ecs describe-task-definition` de `campus-locator-dev-validacion` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Crea el video `validacion-22-<ts>` con 6 fotos declaradas (flujo de BE-2.1) y sube las fotos 1–3 (JPEG sintéticos de 1024×768); cada 15 s lee `GET /v1/admin/videos/{id}` (BE-2.1) | Fotos 1–3 en `procesada` antes de 10 min |
| C1b | SQL `SELECT imagen_id, version_vector FROM embeddings WHERE imagen_id IN (<fotos 1–3>)` | Una fila por foto, con `version_vector = 'dinov2-vitb14/pp-v1'` |
| C1c | `s3api get-object --key thumbs/{video_id}/{imagen_id}.jpg` de las fotos 1–3 | Existen, se decodifican como JPEG y su lado mayor es ≤ 320 px (`MINIATURA_LADO_PX`) |
| C2 | Anota `ApproximateNumberOfMessages` de `sqs_ingesta_dlq_url` (`sqs get-queue-attributes`); sube como foto 4 el texto `validacion-no-es-jpeg` con su URL firmada (`Content-Type: image/jpeg`); espera su `estado` en `GET /v1/admin/videos/{id}` y lee su `error` | `error` antes de 10 min, motivo no vacío y la DLQ con el mismo número de mensajes |
| C3a | Anota `desiredCount` de `embedding`; `ecs update-service --cluster campus-locator-dev --service embedding --desired-count 0` hasta ver `"embedding": "no_disponible"` en `/v1/health/ready`; pide URLs nuevas y sube las fotos 5 y 6; durante 6 min (2 × visibilidad de `ingesta`) muestrea cada 30 s `ApproximateNumberOfMessages` y `ApproximateNumberOfMessagesNotVisible` de `ingesta` | ≥ 2 visibles y 0 en vuelo en cada muestra; `worker` con `runningCount = 1` en la última (`ecs describe-services`); fotos 5 y 6 sin `procesada` |
| C3b | `ecs update-service … --desired-count <anotado>`, `ecs wait services-stable --services embedding` y espera `"embedding": "ok"` | Fotos 5 y 6 en `procesada` antes de 10 min y la DLQ de `ingesta` con el número anotado en C2 |
| C4 | `s3api head-object` de la foto 1 → `ETag`; SQL `SELECT count(*), max(creado_en) FROM embeddings WHERE imagen_id = '<foto 1>'`; `sqs send-message --queue-url <sqs_ingesta_url>` con el evento de §5.8 `{"Records": [{"eventName": "ObjectCreated:Put", "s3": {"bucket": {"name": "campus-locator-dev-dataset-648617469176"}, "object": {"key": "dataset/<video_id>/<foto 1>.jpg", "size": <bytes>, "eTag": "<ETag>"}}}]}`; espera a que `ingesta` no tenga mensajes visibles ni en vuelo (máx. 5 min) y repite el SQL | El mensaje se consumió sin ir a la DLQ, `count = 1` y `max(creado_en)` no cambió |
| C5 | Anota `creado_en` del vector de la foto 2; envía a `ingesta` `{"tipo": "reprocesar_imagen", "version": 1, "imagen_id": "<foto 2>", "solicitado_por": "<usuario.id del admin>", "solicitado_en": "<ahora>"}`; espera como en C4; SQL sobre `embeddings` e `imagenes` | Una sola fila en `embeddings` para la foto 2, con `creado_en` posterior al envío, y la imagen en `procesada` |

Orden de ejecución: C1, C2, C4, C5, C3 (C3 apaga `embedding` y va al final). C5 envía el mensaje directamente porque
`POST /v1/admin/images/{id}/reprocesar` llega con BE-4.1. SQL = tarea `campus-locator-dev-validacion` con `psql -tAc`,
como en [`validation-1-2.md`](./validation-1-2.md) §2.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea el video `validacion-22-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 6 fotos y coordenadas fuera del campus:
cinco JPEG sintéticos (semilla distinta en cada ejecución) y un archivo que no es JPEG. Los dos mensajes que inyecta en
`ingesta` solo nombran imágenes de ese video.

La limpieza siempre devuelve primero `embedding` al `desiredCount` anotado (también si algo falló). Al empezar, si una
ejecución interrumpida dejó `embedding` con `desiredCount = 0` dentro del horario, lo vuelve a 1 antes de P3.

Limpieza (backend `ARCHITECTURE.md` §5.11): al terminar, también si algo falló, borra su video con `limpiar-validacion
--video <id>` en una tarea suelta con la definición `campus-locator-dev-worker` (o con `DELETE /v1/admin/videos/{id}` si
BE-4.1 está «Hecho»). Al empezar, si `GET /v1/admin/videos?q=validacion-` devuelve restos de una ejecución interrumpida,
los borra igual (`limpiar-validacion` sin `--video`).

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate22.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`
(opcionales; ver `ARCHITECTURE.md` §5.11). Durante C3, `/v1/localize` de `dev` responde `503 EMBEDDING_NO_DISPONIBLE`.
Duración aproximada: 30 minutos.
