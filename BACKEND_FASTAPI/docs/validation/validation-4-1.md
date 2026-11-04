# Validación 4-1 — BE-4.1 Administración de videos e imágenes, y purga

| Campo | Valor |
|---|---|
| Lote | `BE-4.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate41.py` |
| Entornos | `dev` (S3, SQS y el `worker` no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-1.3, BE-2.1, BE-2.2, BE-2.4 y BE-3.1; la descripción de `validate41.py`). Cómo
funciona lo que se valida: `ARCHITECTURE.md` §4.12 y ADR-BE-20; contratos en §5.5, §5.7 y §5.8.

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, permisos u hora), sin
crear nada. P5 es la única que cambia algo (enciende `embedding`) y va la última.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | `BE-2.2` y `BE-2.4` en «Hecho», dentro de horario y la API con base | Las filas de `BACKEND_FASTAPI/docs/PLAN.md` §3 dicen `Hecho` (si no: 2); hora de Bogotá antes de las 21:00 (si no: 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: 2) |
| P3 | Login de admin y BE-4.1 desplegado | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es 3); `GET /v1/admin/images?por_pagina=1` → `200` (un `404` es 2: «BE-4.1 sin desplegar») |
| P4 | Recursos para inspeccionar y para parar el `worker` | Outputs `bucket_dataset`, `sqs_purga_url`, `sqs_purga_dlq_url`, `subredes_tareas` y `sg_migrate`; `comprobar_bucket`; definición `campus-locator-dev-validacion`; la última revisión de `campus-locator-dev-worker` con la misma imagen que `api` (si no: 2); lectura de `purga` (`get-queue-attributes`); INF-2.1 (`EmbeddingDev.comprobar_inf21`) y el objetivo escalable de `worker` (`application-autoscaling describe-scalable-targets`) |
| P5 | `embedding` encendido y visto por `api` | Como `validate24.py` P5: si está encendido y `/v1/health/ready` dice `"embedding": "ok"`, solo un latido; si no, lo enciende con el contrato de infra §5.10 y anota cómo lo encontró **antes** de encender. Si no queda listo: 2 |

**Preparación** (tras las precondiciones; un fallo solo se avisa): 1) si el escalado de `worker` quedó suspendido
(`SuspendedState` con algún `true`: una ejecución interrumpida), lo reanuda; 2) borra con `DELETE /v1/admin/videos/{id}`
los videos con `nombre` y `ref_cliente` `validacion-…` (`comun.videos_validacion`: también los de BE-2.1, BE-2.2,
BE-2.3 y BE-2.4); 3) borra los lugares `validacion-…`; 4) anota los mensajes de la DLQ de `purga`. Imprime
`[PREPARACION] …`.

## 2. Comprobaciones automáticas

`<P>` = `validacion-41-<AAAAMMDD-HHMMSS>` (UTC). V1 = video `<P>` con 6 fotos y V2 = `<P>-b` con 2, JPEG en color
(`jpeg_patron`, semilla distinta en cada ejecución) en una coordenada fuera del campus distinta en cada ejecución
(`1.0 + (semilla % 997) · 0,001, −100.0`). La primera comprobación que necesita V1 lo crea, sube sus 6 fotos, llama a
`complete` y espera a que las 6 estén `procesada` (sondeo cada 15 s, máx. 20 min; una en `error` es `falla`) y guarda
su detalle para C5a.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C5b | Sobre V1: `GET /v1/admin/images?video_id=<V1>`; `GET /v1/admin/images/{foto 1}` y descarga su `url_miniatura`; crea el lugar `<P>`; `PATCH` de la foto 4 (`lat` + 0,000045 —≈ 5 m—, `lng`, `lugar_id` del lugar, `calidad: "baja"`, `notas: "validacion-41"`); `POST /v1/admin/images/lote` `reasignar` de las fotos 1–2 al lugar y `eliminar` de la foto 6 más un UUID inexistente; `POST …/{foto 4}/reprocesar`; `DELETE` de la foto 5 dos veces | Lista con `items`, `total` = 6, `pagina`, `por_pagina`, en `orden` y con los campos exactos de `ImagenAdmin`; el detalle con `video` = V1 y `vector.version_vector`; la miniatura `200 image/jpeg`; el `PATCH` `200` con los valores nuevos; lotes `{"procesadas": 2, "fallidas": []}` y `{"procesadas": 1, "fallidas": [{"id": <UUID>, "codigo": "NO_ENCONTRADO"}]}`; `reprocesar` `202` y la foto 4 en `subida` (o ya `procesada` otra vez); `DELETE` `204` y después `404` |
| C4a | `PATCH /v1/admin/videos/{V1}` con `{"nombre": "<P>-renombrado"}` (recortado a 40) | `200` con el nombre nuevo |
| C1a | Envía las fotos 1–3 de V1 a `POST /v1/admin/diagnostico/vecinos?k=5` | Para cada una, su propia `imagen_id` es el primer vecino y su `video_id` es V1 |
| C1b | `DELETE /v1/admin/videos/{V1}` e inmediatamente las mismas tres consultas | `202` con exactamente `id`, `estado = "eliminado"`, `fotos_retiradas` y `purga = "programada"`; ningún vecino de las tres respuestas tiene `video_id` = V1 |
| C4b | SQL `SELECT accion, actor_id FROM auditoria WHERE entidad_id = '<V1>' AND accion IN ('video.renombrar', 'video.eliminar')` (necesita C1b) | Una fila de cada acción, las dos con `actor_id` = `usuario.id` del login |
| C5a | Revisa el detalle de V1 guardado, la respuesta del `PATCH` y `GET /v1/admin/videos?q=validacion-&orden=fecha&dir=desc`; repite el `DELETE` de V1; `GET /v1/admin/videos/{V1}` | `VideoResumen` (y cada `ImagenAdmin` del detalle) con exactamente los campos de §5.5, enumerados válidos y `creado_en` con `Z` sin fracciones; la página con `items`, `total`, `pagina`, `por_pagina`; el `DELETE` repetido da **la misma** respuesta; el `GET` da `404` |
| C2 | Cada 30 s, `list-objects-v2` de `dataset/{V1}/` y `thumbs/{V1}/`; al vaciarse, SQL `SELECT purgado_en IS NOT NULL FROM videos WHERE id = '<V1>'` | Sin objetos antes de 10 min y `t` |
| C3 | Crea V2 y espera sus 2 fotos `procesada`. Anota las réplicas de `worker`, **suspende su escalado** (`register-scalable-target … SuspendedState` con los tres en `true`), lo pone en 0 y espera `runningCount = 0` (máx. 5 min). C3a: `DELETE /v1/admin/videos/{V2}` y, 30 s después, `ApproximateNumberOfMessages` de `purga`. C3b: cada 30 s, hasta 21 min desde el `DELETE` (dos ciclos de `RECONCILIADOR_CADA_MIN` sobre el umbral de 10 min), busca en `/campus-locator/dev/api` un `purgas_reencoladas` con `enviados` ≥ 1. C3c: reanuda el escalado, pone `worker` en 1 y espera la purga de V2 como en C2 | C3a: `202` y ≥ 1 mensaje visible; C3b: el evento aparece y los objetos de `dataset/{V2}/` siguen en S3; C3c: V2 sin objetos antes de 10 min, `purgado_en` no nulo y la DLQ de `purga` sin mensajes nuevos |

Orden: C5b, C4a, C1a, C1b, C4b, C5a, C2, C3. SQL = tarea `campus-locator-dev-validacion` con `psql -tAc`. Las URLs
prefirmadas se usan pero nunca se imprimen.

Lo que **no** comprueba (lo cubren las pruebas con base, `tests/base/test_admin_videos_base.py`): que SQS caído al
borrar una imagen no cambie nada (500), que el reconciliador no reenvíe antes de 10 min, que `purgar_imagen` de una
imagen que sigue existiendo no toque S3, `reprocesar` de una foto sin subir (`409`), `lugar_id` inexistente (`422`),
las URLs según el estado de la foto y el detalle sin S3.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea V1 (6 fotos), V2 (2 fotos) y el lugar `<P>`. Los `PUT` generan 8 eventos en `ingesta` y el `reprocesar`, uno más;
los consume el `worker`. Lanza tareas de `campus-locator-dev-validacion` (`psql`) para C2, C3 y C4b.

**`embedding`**: como `validation-2-3` §4 (contrato de infra §5.10; ~0,10 USD/h mientras está encendido).

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`), en este orden; un fallo en un paso no impide
los siguientes:
1. Si el script suspendió el escalado de `worker` (se marca **antes** de suspender), lo reanuda y le devuelve al menos
   las réplicas anotadas: `escalado de worker reanudado` (o `escalado de worker sin tocar`).
2. Deja `embedding` como lo encontró (los mismos mensajes que `validation-2-3` §4).
3. Borra con `DELETE /v1/admin/videos/{id}` los videos de prueba que no borraron C1b o C3 (la purga limpia S3 cuando
   corre el `worker`) y el lugar con `DELETE /v1/admin/places/{id}`.

Si el script se interrumpe: el escalado de `worker` puede quedar suspendido (lo reanuda la preparación de la siguiente
ejecución, o el paso 7 de §5) y `embedding` encendido hasta las 22:00 o 45 min sin uso.

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Además de lo de `validation-2-3` §5 (secreto, S3, `ecs run-task`/`describe-*`, logs, encendido de `embedding`): `sqs:GetQueueAttributes` de `purga` y su DLQ, `logs:FilterLogEvents` en `/campus-locator/dev/api`, `application-autoscaling:RegisterScalableTarget` y `DescribeScalableTargets` y `ecs:UpdateService` de `worker` (con `campus-admin`, todo) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`. Duración:
35–60 min (encender `embedding`, 3–6 min; procesar V1 y V2, 2–15 min cada uno; C3b, 10–21 min). El informe queda en
`project/.validacion/BE-4.1-<AAAAMMDD-HHMMSS>.json` (UTC) o en `--informe RUTA`. Recursos compartidos (los coordina el
maestro): mientras corre, nadie más enciende o apaga `embedding`, cambia `desiredCount` o el escalado de `worker`, sube
fotos, borra videos o hace push a `main` con cambios en `BACKEND_FASTAPI/project/**` o `SERVICE_EMBEDDING/project/**`;
**mientras dura C3 no hay ingesta en `dev`** (no correrlo durante una recolección).

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo. Sin Docker en la máquina, las pruebas con base se corren en el CI de un PR (`backend.yml` en un PR
   ejecuta `ruff` y `pytest` con PostgreSQL 17 + pgvector y `PRUEBAS_DB_OBLIGATORIA=1`, sin desplegar); en local:

```bash
cd BACKEND_FASTAPI/project
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `… files already formatted` y `778 passed, 274 skipped` (sin `PRUEBAS_DB_URL`). En el
CI del PR: el job de pruebas en verde, ninguna omitida (las 12 de `tests/base/test_admin_videos_base.py` incluidas).

2. Llevar el commit a `main` (cambia el bucle del `worker`: no durante una recolección; el 2026-10-27 se integró en pleno
   día de campo por decisión del usuario, con la ingesta en reposo, y no hubo problema). `backend.yml`
   pasa las pruebas, publica la imagen, ejecuta `migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza
   `api` y `worker`. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que BE-4.1 está (desde `BACKEND_FASTAPI/project`; con la imagen anterior el
   segundo da `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' $URL/admin/images
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `401` (la ruta existe y pide token).

4. Comprobar que `worker` lleva la imagen de `api` y que su escalado no está suspendido:

```bash
export AWS_PROFILE=campus-admin
aws ecs describe-task-definition --task-definition campus-locator-dev-worker --query 'taskDefinition.containerDefinitions[0].image' --output text
aws ecs describe-task-definition --task-definition $(aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].taskDefinition' --output text) --query 'taskDefinition.containerDefinitions[0].image' --output text
aws application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids service/campus-locator-dev/worker --query 'ScalableTargets[0].SuspendedState' --output json
```

Esperado: dos líneas iguales `…/campus-locator/backend:<SHA>` y los tres `…Suspended` en `false`.

5. Mirar la hora, `embedding`, `worker` y las colas (solo lectura):

```bash
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_purga_url) --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_purga_dlq_url) --attribute-names ApproximateNumberOfMessages --output text
```

Esperado: antes de las **21:00**; `embedding 0 0` y `worker 0 0` (el script los enciende y al final los apaga) o
`embedding 1 1`; `purga` con `0` y `0` (si tiene mensajes, el `worker` los purgará al encender: no es un fallo) y su DLQ
con `0`.

**Ejecución.**

6. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate41.py --entorno dev
```

Esperado (35–60 min; el progreso del encendido sale por stderr): código 0 con `[PASA]` en P1–P5 y en C5b, C4a, C1a,
C1b, C4b, C5a, C2 y C3. P2 termina en `BE-2.2 y BE-2.4 «Hecho» · https://…/v1 · /v1/health/ready → "db": "ok" · HH:MM
en Bogotá`; P3, `login admin 200 (rol admin) · GET /v1/admin/images → 200`; P4, `bucket, purga y su DLQ,
campus-locator-dev-worker:<n> con la imagen de api · INF-2.1: …`; P5, `embedding encendido en N s · …` (o `ya encendido
(latido publicado)`); `[PREPARACION] sin restos validacion- · sin lugares validacion- de ejecuciones anteriores · DLQ de
purga: 0`; C5b `V1 con 6 fotos procesadas en N min · …`; C4a `PATCH /v1/admin/videos/{V1} → 200 con el nombre nuevo
(…)`; C1a `fotos (1, 2, 3) son su propio primer vecino (similitud […])`; C1b `DELETE → 202 4 fotos retiradas · ningún
vecino de V1 en las 3 consultas siguientes` (4: la 5 y la 6 ya se borraron en C5b); C4b `auditoria: video.renombrar y
video.eliminar de V1, una cada una, con actor_id = el admin`; C5a `detalle, PATCH y lista con los campos de §5.5 ·
DELETE repetido igual · GET del video borrado → 404`; C2 `dataset/ y thumbs/ de V1 vacíos en N min · purgado_en no
nulo`; C3 `V2 procesado en N min · worker en 0 · DELETE V2 → 202, purga con ≥ 1 mensajes · reconciliador: n reenviados
(… visibles) con los objetos aún en S3 · worker de vuelta: V2 purgado en N min, DLQ 0`; y al final `[LIMPIEZA] escalado
de worker sin tocar · embedding apagado (lo encendió el validador) · videos de prueba borrados al final: 0 (la purga
limpia S3) · lugares: 1` (o `embedding sigue encendido (como estaba)`) y `== Resultado: pasa (código 0)`. Con eso, el
maestro pasa la fila BE-4.1 de PLAN §3 a «Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

7. Solo si el script se interrumpió: reanudar el escalado de `worker` y, si en el paso 5 `embedding` estaba apagado,
   apagarlo con la herramienta de infra (infra §5.11), y comprobarlo:

```bash
aws application-autoscaling register-scalable-target --service-namespace ecs --resource-id service/campus-locator-dev/worker --scalable-dimension ecs:service:DesiredCount --suspended-state DynamicScalingInSuspended=false,DynamicScalingOutSuspended=false,ScheduledScalingSuspended=false
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: sin salida el primero, código 0 el segundo y las líneas `embedding 0` y `worker 0`. Los videos y el lugar de
prueba los borra la preparación de la siguiente ejecución.

En `local` no se ejecuta: el script termina con 3 (`BE-4.1 solo admite el entorno: dev`). Lo que sí se comprueba en
`local` está en el paso 1: los endpoints y la purga contra PostgreSQL (`tests/base/test_admin_videos_base.py`, en el
CI), el contrato (`tests/contrato/test_contrato_admin.py`), la purga y el reconciliador sin base
(`tests/unit/test_purga.py`) y el validador contra un mundo falso con backends defectuosos
(`tests/ops/test_validate41.py`).
