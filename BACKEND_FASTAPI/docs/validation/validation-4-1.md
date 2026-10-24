# Validación 4-1 — BE-4.1 Administración de videos e imágenes, y purga

| Campo | Valor |
|---|---|
| Lote | `BE-4.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate41.py` |
| Entornos | `dev` (necesita S3 y SQS, que no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | Login de admin | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` |
| P3 | `BE-2.2` en «Hecho», dentro del horario | `PLAN.md` §3 marca BE-2.2 «Hecho»; `GET /v1/health/ready` → `"embedding": "ok"`; hora `America/Bogota` entre 06:00 y 21:00 |
| P4 | `BE-2.4` en «Hecho»: búsqueda de vecinos | `PLAN.md` §3 marca BE-2.4 «Hecho»; `POST /v1/admin/diagnostico/vecinos?k=1` con una foto sintética → `200` |
| P5 | Escalado de `worker` controlable | `application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids service/campus-locator-dev/worker` devuelve el objetivo |
| P6 | Recursos para inspeccionar | Outputs `bucket_dataset`, `sqs_purga_url`, `sqs_purga_dlq_url`, `subredes_tareas` y `sg_migrate`; `ecs describe-task-definition` de `campus-locator-dev-validacion` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Con las fotos 1–3 de V1 en `procesada` (V1 tiene 6 fotos en la coordenada X, ver §4), envía cada una a `POST /v1/admin/diagnostico/vecinos?k=5` | Para cada foto, su propia `imagen_id` es el primer vecino y su `video_id` es V1 |
| C1b | `DELETE /v1/admin/videos/{V1}` e inmediatamente las mismas tres consultas | `202` con `estado = "eliminado"` y `purga = "programada"`; ningún vecino de las tres respuestas tiene `video_id` = V1 |
| C2 | Cada 30 s, `s3api list-objects-v2 --prefix dataset/{V1}/` y `--prefix thumbs/{V1}/`; al vaciarse, SQL `SELECT purgado_en FROM videos WHERE id = '<V1>'` | `KeyCount = 0` en ambos antes de 10 min y `purgado_en` no nulo |
| C3a | Crea V2 (2 fotos, `procesado`); suspende el escalado de `worker` (`application-autoscaling register-scalable-target … --suspended-state DynamicScalingInSuspended=true,DynamicScalingOutSuspended=true,ScheduledScalingSuspended=true`), `ecs update-service --service worker --desired-count 0` y espera `runningCount = 0`; `DELETE /v1/admin/videos/{V2}`; anota `ApproximateNumberOfMessages` de `purga` | `202` y al menos 1 mensaje en `purga` |
| C3b | Durante hasta 21 min (dos ciclos de `RECONCILIADOR_CADA_MIN` sobre el umbral de 10 min) muestrea `ApproximateNumberOfMessages` de `purga` | Sube al menos en 1 sobre lo anotado (re-encolado de `purgar_video`) mientras los objetos de V2 siguen en S3 |
| C3c | Reanuda el escalado (`--suspended-state` con los tres en `false`) y `update-service --desired-count 1`; espera a que `purga` se vacíe | Antes de 10 min, `dataset/{V2}/` y `thumbs/{V2}/` sin objetos, `purgado_en` de V2 no nulo y `sqs_purga_dlq_url` sin mensajes nuevos |
| C4 | `PATCH /v1/admin/videos/{V1}` con `{"nombre": "validacion-41-<ts>-renombrado"}` antes de C1b; después de C1b, SQL `SELECT accion, actor_id FROM auditoria WHERE entidad_id = '<V1>' AND accion IN ('video.renombrar', 'video.eliminar')` | `PATCH` `200` con el nombre nuevo; una fila por acción, ambas con `actor_id` = `usuario.id` del admin |
| C5a | Valida contra §5.5 y §5.1 las respuestas de `GET /v1/admin/videos?q=validacion-&orden=fecha&dir=desc&por_pagina=24`, `GET /v1/admin/videos/{V1}`, el `PATCH` de C4, el `DELETE` de C1b repetido y `GET /v1/admin/videos/{V1}` tras borrarlo | Página con `items`, `total`, `pagina`, `por_pagina`; `VideoResumen` y `fotos` con todos sus campos, tipos y enumerados; el `DELETE` repetido da la misma respuesta; el `GET` final da `404 NO_ENCONTRADO` |
| C5b | Sobre V1, antes de C1b: `GET /v1/admin/images?video_id=<V1>`, `GET /v1/admin/images/{foto 1}`, `PATCH` de la foto 4 (`lat`+`lng` desplazados 5 m, `lugar_id` del lugar de prueba, `calidad: "baja"`, `notas: "validacion-41"`), `POST /v1/admin/images/lote` con `reasignar` de las fotos 1–2 y con `eliminar` de la foto 6 más un uuid inexistente, `POST /v1/admin/images/{foto 4}/reprocesar`, `DELETE /v1/admin/images/{foto 5}`; descarga `url_miniatura` de la foto 1 | `ImagenAdmin` completo con `vector.version_vector` en las `procesada`; `PATCH` `200` con los valores nuevos; lotes con `procesadas` 2 y 1 y el uuid en `fallidas` con `NO_ENCONTRADO`; `reprocesar` `202` y foto 4 en `subida`; `DELETE` `204` y luego `404`; miniatura `200` `image/jpeg` |

Orden de ejecución: C5b, C4 (`PATCH`), C1a, C1b, C4 (auditoría), C5a, C2, C3. SQL = tarea
`campus-locator-dev-validacion` con `psql -tAc`, como en [`validation-1-2.md`](./validation-1-2.md) §2. Las URLs
prefirmadas se usan pero nunca se imprimen.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea, con el flujo de BE-2.1, los videos V1 `validacion-41-<ts>` (6 fotos) y V2 `validacion-41-<ts>-b` (2 fotos), y el
lugar `validacion-41-<ts>`. Las fotos son JPEG sintéticos con semilla distinta en cada ejecución y están en una
coordenada X fuera del campus, distinta en cada ejecución, para que C1 no encuentre restos de otras pruebas.

La limpieza siempre reanuda el escalado de `worker` (`--suspended-state` con los tres en `false`) y le devuelve al menos
el `desiredCount` anotado; borra el lugar con `DELETE /v1/admin/places/{id}` y, si C1b o C3a no llegaron a correr,
V1 y V2 con `DELETE /v1/admin/videos/{id}` (la purga limpia S3). Al empezar: si una ejecución anterior dejó el
escalado suspendido (`SuspendedState` en `describe-scalable-targets`), lo reanuda; borra los videos de
`GET /v1/admin/videos?q=validacion-` cuyo `nombre` empiece por `validacion-` (también los que dejaron BE-2.1, BE-2.2 y
BE-2.3) y los lugares `validacion-`.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate41.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria; también cambia el escalado y las réplicas de `worker`), `VALIDACION_API_URL`,
`VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD` (opcionales; ver `ARCHITECTURE.md` §5.11). Mientras dura C3 la
ingesta de `dev` queda detenida. Duración aproximada: 45 minutos.
