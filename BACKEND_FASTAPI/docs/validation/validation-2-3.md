# Validación 2-3 — BE-2.3 Resumen del panel

| Campo | Valor |
|---|---|
| Lote | `BE-2.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate23.py` |
| Entornos | `dev` (las fotos `procesada` necesitan S3, SQS y el `worker`, que no se emulan en `local`) |
| Criterios | Automáticos: C1 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-1.3, BE-2.1, BE-2.2, BE-3.1 y BE-2.3; la descripción de `validate23.py`). Cómo
funciona el endpoint: `ARCHITECTURE.md` §4.7; su contrato, §5.5 («`GET /v1/admin/stats` (BE-2.3)»).

`alertas_activas` no se comprueba con datos aquí: las alertas salieron del núcleo a BE-3.3 (ARCHITECTURE 0.11.0), cuyo
C5 lo hace (y necesita BE-2.3 «Hecho»). Este lote solo exige que el campo exista y sea un entero ≥ 0 (0 mientras no
haya alertas).

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, permisos u hora), sin
crear nada. P5 es la única que cambia algo (enciende `embedding`), va la última y solo se evalúa si C1a está incluida
(con `--solo C1b,C1c` no hace falta `embedding`).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | `BE-2.2` y `BE-3.1` en «Hecho», dentro de horario y la API con base | Las filas `BE-2.2` y `BE-3.1` de `BACKEND_FASTAPI/docs/PLAN.md` §3 dicen `Hecho` (si no: código 2); si C1a está incluida, hora de Bogotá antes de las 21:00 (si no: código 3; `embedding` se apaga solo a las 22:00); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: código 2) |
| P3 | Login de admin, BE-2.3 y BE-3.1 desplegados | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es código 3); `GET /v1/admin/stats` → `200` (un `404` es código 2: «BE-2.3 sin desplegar»); `GET /v1/admin/places` → `200` |
| P4 | Recursos para subir fotos y borrar el video, e INF-2.1 | Outputs `bucket_dataset` y `sqs_ingesta_url` y `comprobar_bucket`; lectura de los contadores de `ingesta` (`get-queue-attributes`); outputs `subredes_tareas` y `sg_migrate`; la última revisión de `campus-locator-dev-worker` con **la misma imagen** que el servicio `api` (si no: código 2, «BE-2.3 sin desplegar del todo»). Si C1a está incluida, objetivos escalables de `embedding` y `worker`, política `campus-locator-dev-worker-cola` y acción `campus-locator-dev-embedding-apagar-noche` (`EmbeddingDev.comprobar_inf21`; si falta: código 2) |
| P5 | `embedding` encendido y visto por `api` (solo con C1a) | Si `embedding` tiene `desiredCount ≥ 1` y `/v1/health/ready` dice `"embedding": "ok"`: solo publica un latido (`EmbeddingEncendidos`). Si no: lo enciende con el contrato de infra §5.10 (§4) y espera a `"embedding": "ok"`. Anota cómo lo encontró **antes** de encender (la limpieza lo apaga aunque el encendido falle a medias). Si no queda listo: código 2 |

**Preparación** (tras las precondiciones; un fallo solo se avisa):
1. Si `GET /v1/admin/videos?q=validacion-` (todas las páginas) tiene restos con `nombre` **y** `ref_cliente`
   `validacion-…`, lanza `limpiar-validacion` sin `--video` (`comun.borrar_restos`).
2. Borra los lugares cuyo nombre normalizado empieza por `validacion-` (de cualquier lote; `comun.borrar_lugares_restos`).

Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

`<P>` = `validacion-23-<AAAAMMDD-HHMMSS>` (hora UTC de la ejecución). Todas las lecturas son `GET /v1/admin/stats`
(`comun.resumen_panel`), y cada una exige `200`, exactamente los campos `total_fotos`, `total_lugares`,
`alertas_activas` y `ultimo_video`, y los tres totales enteros ≥ 0. Las cifras son globales: cada comprobación lee las
suyas justo antes y después de crear sus datos y compara diferencias.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Espera a que `ingesta` no tenga mensajes visibles ni en vuelo (cada 15 s, máx. **15 min**: el `worker` procesaría fotos ajenas entre s0 y s1). Lee s0. Crea el video `<P>` (2 fotos declaradas, coordenadas `1.0, -100.0`) y registra 2 JPEG sintéticos de 1024×768 (flujo de BE-2.1); lee otra vez. Sube las 2 fotos con sus URL y lee `GET /v1/admin/videos/{id}` cada 15 s hasta que las 2 estén `procesada` (máx. **20 min**: si `worker` estaba en 0, su subida tarda de 2 a 15 min, infra ADR-INF-15). Lee s1 | Con las 2 fotos en `pendiente_subida`, `total_fotos` = el de s0 (solo cuentan las `procesada`); ninguna foto en `error` (sería `falla` inmediata); `s1.total_fotos − s0.total_fotos = 2` |
| C1b | Lee; `POST /v1/admin/places` de `<P> a` y `<P> b` (`categoria: "bloque"`, en `1.0, -100.0`); lee; `DELETE /v1/admin/places/{b}`; lee | `201` en los dos y `total_lugares` sube en 2; `204` y `total_lugares` baja en 1 |
| C1c | Lee (si C1a no corrió, antes crea el video `<P>` sin fotos) | `ultimo_video` es un objeto con exactamente `numero` y `creado_en`; `creado_en` con el formato `AAAA-MM-DDTHH:MM:SSZ` (sin fracciones); `ultimo_video` = `{numero, creado_en}` del `VideoResumen` que devolvió `POST /v1/collect/videos` al crear el video; `alertas_activas` entero ≥ 0 |

Orden: C1a, C1b, C1c. Si una diferencia no cuadra, el detalle muestra los valores leídos para descartar actividad
ajena antes de repetir (el script supone que nadie sube fotos, crea o borra videos o lugares en `dev` mientras corre).
El script nunca imprime tokens, contraseñas ni URLs prefirmadas.

Lo que **no** comprueba (lo cubren las pruebas con base, `tests/base/test_estadisticas_base.py`): que las fotos de un
video eliminado no cuenten y que un video eliminado no sea el último (no hay borrado de videos hasta BE-4.1), las
fotos en `error`, el desempate por `numero`, `ultimo_video = null` sin videos, y `alertas_activas` con alertas (BE-3.3).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea el video `validacion-23-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 2 JPEG sintéticos (semilla distinta en
cada ejecución) en una coordenada fuera del campus; sus `PUT` generan 2 eventos en `ingesta`, que consume el `worker`.
Crea los lugares `validacion-23-<AAAAMMDD-HHMMSS> a` y `… b` en `1.0, -100.0` (no en (0.001, 0.001), el punto de
`validate31.py`); `b` lo borra la propia C1b. No crea alertas ni usuarios. Lanza 1 tarea suelta de
`campus-locator-dev-worker` (`limpiar-validacion` al final) y otra al empezar si había restos.

**`embedding`** (solo con C1a; infra §5.10 y §5.11; `comun.EmbeddingDev.encender`, el mismo contrato que
`embedding.py encender` de infra): 1) `RegisterScalableTarget` 0-1 de `embedding` y `worker`; 2) `PutMetricData` de
`EmbeddingEncendidos` = 1 en `campus-locator/dev`; 3) espera a que `GetMetricStatistics` la devuelva, un minuto más y
que la alarma `campus-locator-dev-embedding-inactivo` no esté en `ALARM` (hasta 5 min); 4) `UpdateService` de
`embedding` a 1; 5) espera tarea `HEALTHY`, despliegue `COMPLETED` y esa tarea registrada en Cloud Map (`servicediscovery
list-instances` con su IP privada, ARCHITECTURE §5.11 «Trampa del arranque») (hasta 10 min desde el paso 1) y, además,
`"embedding": "ok"` en `/v1/health/ready` (hasta 2 min). Cuesta ~0,10 USD/h mientras está encendido.

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`, que deja también `embedding` como esté), en este
orden; un fallo en un paso no impide los siguientes:
1. Deja `embedding` como lo encontró: si lo encendió el script (P5), lo apaga como `embedding.py apagar` (rango 0-0 y
   `desiredCount = 0` de `embedding` y `worker`; no espera a que paren); si estaba encendido y quedó en 0, lo vuelve a
   encender con el contrato. Imprime `embedding apagado (lo encendió el validador)`, `embedding sigue encendido (como
   estaba)`, `embedding vuelto a encender (estaba encendido)` o, sin P5, `embedding sin tocar`; si no lo consigue,
   `… embedding NO quedó como estaba …` (entonces, paso 7 de §5).
2. Borra su video con `limpiar-validacion --video <id>` (tarea suelta con `campus-locator-dev-worker`, ARCHITECTURE
   §5.11; con `DELETE /v1/admin/videos/{id}` cuando BE-4.1 esté «Hecho»): filas (en cascada fotos y vectores) y
   objetos de `dataset/` y `thumbs/`.
3. Borra con `DELETE /v1/admin/places/{id}` los lugares con el prefijo de la ejecución que sigan existiendo y los que
   apuntó (`comun.borrar_lugares`).

Si el script se interrumpe (Ctrl+C, terminal cerrada): `embedding` puede quedar encendido hasta las 22:00 o hasta 45
min sin uso (paso 7 de §5); el video y los lugares los borra la preparación de la siguiente ejecución (o la de
`validate21.py`, `validate24.py`, `validate31.py`…).

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Necesita leer el secreto `admin-inicial` (si no se pasan `VALIDACION_ADMIN_*`); `head-bucket`, `head-object` y `list-objects-v2` en el bucket del dataset; `sqs:GetQueueAttributes` de `ingesta`; `ecs run-task`/`describe-*` en `campus-locator-dev` con `iam:PassRole` del rol de `worker`; `logs:GetLogEvents` en `/campus-locator/dev/worker`; y, para el encendido, `application-autoscaling:Describe*` y `RegisterScalableTarget`, `cloudwatch:PutMetricData`, `GetMetricStatistics` y `DescribeAlarms`, `ecs:UpdateService`, `ListTasks` y `DescribeTasks`, y `servicediscovery:ListInstances` (con `campus-admin`, todo). `terraform output` lee el estado de `envs/dev` |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`. Duración:
10–40 min con C1a (encender `embedding`, 3–6 min; subir `worker` desde 0 y procesar, 2–15 min), menos de 1 min con
`--solo C1b,C1c`. El informe queda en `project/.validacion/BE-2.3-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe
RUTA`. Recursos compartidos (los coordina el maestro): mientras corre, nadie más enciende o apaga `embedding`, cambia
`desiredCount` de `worker`, deja mensajes en `ingesta`, sube fotos, crea o borra videos o lugares en `dev` (los
validadores de BE-2.1, BE-2.2, BE-2.4, BE-3.1 y BE-4.1 también crean datos de prueba y la preparación de cada uno borra
los `validacion-` de los demás), ni hace push a `main` con cambios en `BACKEND_FASTAPI/project/**` o
`SERVICE_EMBEDDING/project/**`. Llamar a `POST /v1/localize` a la vez no cambia ninguna cifra, pero compite por
`embedding`.

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo en la máquina, con el PostgreSQL del compose para las pruebas `base`:

```bash
cd BACKEND_FASTAPI/project
docker compose up -d --wait db
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `… files already formatted` y `… passed` sin fallos ni omitidas (874 en `012e0ae`).

Si el puerto 5432 está ocupado por el compose de otra copia, se aísla con otro proyecto y otro puerto (sin tocar el
`docker-compose.yml`), y al terminar se baja solo ese proyecto (sin comprobar: Docker no arrancó al construir BE-2.3;
`COMPOSE_PROJECT_NAME` tiene prioridad sobre el `name:` del archivo según la documentación de Docker Compose):

```bash
COMPOSE_PROJECT_NAME=fuera-be23 DB_PUERTO_LOCAL=55432 docker compose up -d --wait db
PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:55432/campus_locator PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
COMPOSE_PROJECT_NAME=fuera-be23 docker compose down
```

Si Docker no arranca en la máquina (como al construir BE-2.3: Docker Desktop se cerraba con un error sobre un socket
viejo en `%LOCALAPPDATA%\Docker\run`), las pruebas con base se corren en el CI: un PR con la rama dispara `backend.yml`,
que en un PR ejecuta `ruff` y `pytest` con un PostgreSQL 17 + pgvector efímero y `PRUEBAS_DB_OBLIGATORIA=1` **sin
desplegar** (ARCHITECTURE §4.2 y §4.3). Esperado: el job de pruebas en verde con `… passed` sin omitidas (así se
comprobó BE-2.3: PR 9, run 40374138268, 874 pasan).

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
`migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker`. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que el endpoint existe (desde `BACKEND_FASTAPI/project`; con la imagen
anterior a BE-2.3, el segundo da `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' $URL/admin/stats
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `401` (la ruta existe y pide token).

4. Comprobar que la revisión de `worker` lleva la misma imagen que `api` (si no, P4 termina con 2):

```bash
export AWS_PROFILE=campus-admin
aws ecs describe-task-definition --task-definition campus-locator-dev-worker --query 'taskDefinition.containerDefinitions[0].image' --output text
aws ecs describe-task-definition --task-definition $(aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].taskDefinition' --output text) --query 'taskDefinition.containerDefinitions[0].image' --output text
```

Esperado: dos líneas iguales, `…/campus-locator/backend:<SHA del commit>`.

5. Mirar la hora, el estado de `embedding` y `worker` y la cola `ingesta` (solo lectura):

```bash
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_ingesta_url) --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --output text
```

Esperado: una hora **antes de las 21:00**; `embedding 0 0` y `worker 0 0` (apagados: el script los enciende y al
final los apaga) o `embedding 1 1` (encendido: lo deja encendido); y la cola con `0` y `0` (si tiene mensajes, por
ejemplo de un recorrido real subido con `embedding` apagado, C1a espera hasta 15 min a que el `worker` la vacíe; si
son muchos, conviene procesarlos antes con `embedding` encendido).

**Ejecución.**

6. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate23.py --entorno dev
```

Esperado (10–40 min; el progreso del encendido sale por stderr): código 0, con `[PASA]` en P1–P5 y en C1a, C1b y C1c.
P2 termina en `BE-2.2 y BE-3.1 «Hecho» · https://…/v1 · /v1/health/ready → "db": "ok" · HH:MM en Bogotá`; P3 es
`login admin 200 (rol admin) · GET /v1/admin/stats → 200 · GET /v1/admin/places → 200`; P4, `bucket, ingesta y
campus-locator-dev-worker:<n> con la imagen de api · INF-2.1: objetivos de embedding y worker,
campus-locator-dev-worker-cola y campus-locator-dev-embedding-apagar-noche`; P5, `embedding encendido en N s ·
/v1/health/ready → "embedding": "ok"` (o `embedding ya encendido (latido publicado) · …`); después `[PREPARACION] sin
restos validacion- de ejecuciones anteriores · sin lugares validacion- de ejecuciones anteriores`; C1a `ingesta vacía ·
total_fotos s0 = <F> · con 2 fotos registradas sin subir, igual · fotos 1–2 en procesada en N min · s1 = <F+2> (+2)`;
C1b `total_lugares <L> → <L+2> (+2, lugares a y b) → <L+1> (−1, b borrado)`; C1c `ultimo_video = numero <n>, creado_en
AAAA-MM-DDTHH:MM:SSZ (el video de prueba) · alertas_activas = 0 (entero ≥ 0) · campos exactos de §5.5`; y al final
`[LIMPIEZA] embedding apagado (lo encendió el validador) · videos de prueba borrados: {"videos": 1, "objetos": 4} ·
lugares de prueba borrados: 1` (o `embedding sigue encendido (como estaba) · …`) y `== Resultado: pasa (código 0)`.
Con eso, el maestro pasa la fila BE-2.3 de PLAN §3 a «Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

7. Solo si el script se interrumpió (o la limpieza dijo `embedding NO quedó como estaba`) y en el paso 5 `embedding`
estaba apagado: apagarlo con la herramienta de infra (infra §5.11) y comprobarlo:

```bash
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: código 0 y las líneas `embedding 0` y `worker 0`. Los restos del video y de los lugares los borra la
preparación de la siguiente ejecución.

En `local` no se ejecuta (S3, SQS y el `worker` no se emulan): el script termina con 3 (`BE-2.3 solo admite el
entorno: dev`). Lo que sí se comprueba en `local` está en las pruebas del paso 1: el endpoint con PostgreSQL real
(`tests/base/test_estadisticas_base.py` cubre C1 y lo que el validador no puede crear en `dev`), el contrato
(`tests/contrato/test_contrato_estadisticas.py`) y el validador contra un mundo falso con interruptores de backend
defectuoso (`tests/ops/test_validate23.py`).
