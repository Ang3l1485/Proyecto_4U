# Validación 5-1 — BE-5.1 Corrección visual (`POST /v1/localize/frame`)

| Campo | Valor |
|---|---|
| Lote | `BE-5.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate51.py` |
| Entornos | `dev` (S3, SQS y el `worker` no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |
| Hora límite para empezar | **21:00 de Bogotá** (UTC−5): dura 5–25 min y `embedding` se apaga solo a las 22:00 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de `comun.py` y «`validate51.py`»). Cómo funciona el endpoint: `ARCHITECTURE.md` §4.14
y ADR-BE-21; su contrato, §5.3; la fila de `eventos_localizacion`, §5.7 («filas de BE-5.1»).

**No depende del dataset real ni de la calibración de BE-3.2:** crea su propio video de prueba con fotos idénticas a
las de las consultas (similitud ~0,999) en dos puntos fuera del campus. Por eso su «Para validar» es BE-2.2 y BE-4.1, y
no BE-3.2 (que sigue «En curso» hasta calibrar).

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, permisos u hora), sin
crear nada. P5 es la única que cambia algo (enciende `embedding` si está apagado) y va la última.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | `BE-2.2` y `BE-4.1` en «Hecho», dentro de horario y la API con base | Sus filas de `BACKEND_FASTAPI/docs/PLAN.md` §3 dicen `Hecho` (si no: 2); hora de Bogotá antes de las 21:00 (si no: 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: 2) |
| P3 | Login de admin y BE-5.1 desplegado | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es 3); `POST /v1/localize/frame` con una sola parte `otra` (sin foto: no llama a embeddings ni deja evento) → `400 FOTOS_INVALIDAS` (un `404` o un `501` es 2: «BE-5.1 sin desplegar») |
| P4 | Recursos para leer la base | Outputs `subredes_tareas` y `sg_migrate` (`comun.red_tareas`) y la definición `campus-locator-dev-validacion` (si falta: 2; sin permiso: 3) |
| P5 | `embedding` encendido y visto por `api` | Como `validate41.py` P5: si está encendido y `/v1/health/ready` dice `"embedding": "ok"`, solo un latido; si no, lo enciende con el contrato de infra §5.10 y anota cómo lo encontró **antes** de encender. Si no queda listo: 2 |

**Preparación** (tras las precondiciones; un fallo solo se avisa): borra con `DELETE /v1/admin/videos/{id}` los videos
cuyo `nombre` **y** `ref_cliente` empiezan por `validacion-51-` (restos de una ejecución interrumpida). **Nunca** toca
otros videos: ni los `validacion-` de otros lotes ni el dataset real. Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

`<P>` = `validacion-51-<AAAAMMDD-HHMMSS>` (UTC). El video `<P>` tiene 4 fotos JPEG en color (`jpeg_patron`, semilla
distinta en cada ejecución): las fotos 1 y 2 en **A** = (2,0 + (semilla % 997) · 0,001, −101,0) y las 3 y 4 en **B**,
300 m al norte de A (océano Pacífico: lejos del campus y de los datos de otros validadores). La primera comprobación
que necesita el video lo crea, sube las 4 fotos, llama a `complete` y espera a que estén `procesada` (sondeo cada 15 s,
máx. 20 min; una en `error` es `falla`). Cada consulta es un `POST /v1/localize/frame` con la foto 1 tal cual se subió
y `metadatos` = `{"rumbo": 90.0, "posicion_previa": {…}, "app_version": "<P>"}` (más `radio_m` en C3); una respuesta
válida debe ser `200` con exactamente los campos de `FrameRespuesta` (§5.3). Distancias por haversine (R = 6 371 008,8
m).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C4 | 7 peticiones mal formadas (no llaman a embeddings): sin parte `metadatos`; sin `posicion_previa`; `posicion_previa.lat` = 91; `radio_m` = 500; `rumbo` = 360; dos partes `foto`; una foto `image/png` | Las cinco primeras dan `422 VALIDACION` con `detalle.campos` = `[metadatos]`, `[metadatos.posicion_previa]`, `[metadatos.posicion_previa.lat]`, `[metadatos.radio_m]` y `[metadatos.rumbo]`; las dos últimas, `400 FOTOS_INVALIDAS` con `indice` 1 y 0 |
| C1 | Foto 1 con la posición previa 15 m al este de A, sin `radio_m` | `resultado = "ok"`, posición a ≤ 10 m de A, `nivel = "alta"`, `radio_busqueda_m` = 40, `imagenes_en_radio` ≥ 2 y `distancia_previa_m` a ≤ 1 m de la distancia real entre la previa y la posición |
| C2 | Foto 1 con la posición previa 10 m al este de B (A queda a ~300 m, fuera del radio) | La posición **no** está a ≤ 100 m de A (`sin_coincidencias`, o `ok` en B si las fotos de B se parecen) e `imagenes_en_radio` ≥ 2 (las de B: hay dataset en el radio, lo que deja fuera a A es el filtro) |
| C3 | Foto 1 con la posición previa 60 m al sur de A, primero con `radio_m` = 30 y después con `radio_m` = 100 | Con 30: `sin_coincidencias`, `imagenes_en_radio` = 0 y `radio_busqueda_m` = 30. Con 100: `ok` a ≤ 10 m de A, `radio_busqueda_m` = 100 y `distancia_previa_m` coherente (±1 m) |
| C6 | Revisa las respuestas `200` de C1, C2 y C3 | Todas con `latencia_ms` ≤ 1 000 (el detalle da la mediana, la máxima y la mediana medida en el cliente, que no cuenta) |
| C5 | SQL `SELECT origen, resultado, fotos_usadas, fotos_con_coincidencia FROM eventos_localizacion WHERE app_version = '<P>' ORDER BY id` | Una fila por cada `200` de esta ejecución (4 en una ejecución completa), en el mismo orden, con `origen = frame`, el mismo `resultado`, `fotos_usadas = 1` y `fotos_con_coincidencia` = 1 con `ok` y 0 con `sin_coincidencias`; ninguna de las peticiones de C4 |

Orden: C4, C1, C2, C3, C6, C5. SQL = tarea `campus-locator-dev-validacion` con `psql -tAc`. Con `--solo C5` o `--solo
C6` sin otras, antes hace la petición de C1 (así hay algo que revisar). Las URLs prefirmadas se usan para subir las
fotos, pero nunca se imprimen.

Lo que **no** comprueba (lo cubren las pruebas locales): `503 EMBEDDING_NO_DISPONIBLE` con `embedding` apagado, `400
SOLICITUD_INVALIDA` (multipart o JSON rotos), el cuerpo de más de 1,6 MB, el borde exacto del radio y que la consulta
no use el índice HNSW (`tests/api/test_localizar_frame.py` y `tests/base/test_frame_base.py`).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos. La prueba en el teléfono la hace FE-5.3.

## 4. Datos de prueba y limpieza

Crea el video `<P>` (4 fotos; sus `PUT` generan 4 eventos en `ingesta`, que consume el `worker`) y lanza 1 tarea de
`campus-locator-dev-validacion` (C5). Cada `200` deja una fila anónima en `eventos_localizacion` (4 en una ejecución
completa, `app_version = <P>`); no hay endpoint para borrarlas y caducan a los 180 días (`EVENTOS_RETENCION_DIAS`).

**`embedding`**: como `validation-2-3` §4 (contrato de infra §5.10; ~0,10 USD/h mientras está encendido). El
2026-10-28 está encendido todo el día por decisión del usuario: el script lo encuentra encendido, publica un latido y
no lo apaga.

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`), en este orden; un fallo en un paso no impide el
siguiente:
1. Borra con `DELETE /v1/admin/videos/{id}` el video `<P>` (la purga limpia S3 cuando corre el `worker`): `video de
   prueba borrado (la purga limpia S3)` (o `sin video de prueba que borrar`).
2. Deja `embedding` como lo encontró: `embedding sigue encendido (como estaba)` o `embedding apagado (lo encendió el
   validador)`.

Si el script se interrumpe: el video `<P>` queda (lo borra la preparación de la siguiente ejecución) y `embedding`
encendido hasta las 22:00 o 45 min sin uso.

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Secreto `campus-locator/dev/admin-inicial`, `ecs run-task`/`describe-*` de `campus-locator-dev-validacion`, logs de `/campus-locator/dev/validacion`, encendido de `embedding` (como `validation-2-3` §5) (con `campus-admin`, todo) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`. Duración:
5–25 min (procesar las 4 fotos, 2–15 min con el `worker` arrancando desde 0; las consultas, segundos). El informe queda
en `project/.validacion/BE-5.1-<AAAAMMDD-HHMMSS>.json` (UTC) o en `--informe RUTA`. Recursos compartidos (los coordina
el maestro): mientras corre, nadie más enciende o apaga `embedding` ni hace push a `main` con cambios en
`BACKEND_FASTAPI/project/**`. Puede correr mientras el usuario se ubica o sube recorridos (solo añade 4 fotos a la cola
`ingesta` y 4 filas a `eventos_localizacion`); si la cola está muy cargada, C1 tarda más en empezar.

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo. Sin Docker en la máquina, las pruebas con base se corren en el CI de un PR (`backend.yml` en un PR
   ejecuta `ruff` y `pytest` con PostgreSQL 17 + pgvector y `PRUEBAS_DB_OBLIGATORIA=1`, sin desplegar); en local:

```bash
cd BACKEND_FASTAPI/project
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `160 files already formatted` y `833 passed, 282 skipped` (sin `PRUEBAS_DB_URL` se
omiten las `base`; medido en WSL el 2026-10-28 sobre la rama de BE-5.1). En el CI del PR: el job de pruebas en verde, ninguna omitida (las 8 de
`tests/base/test_frame_base.py` incluidas).

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica la imagen, ejecuta `migrate` (sin migraciones
   nuevas: `aplicada = false`) y actualiza `api` y `worker`. No cambia `/v1/localize` ni la ingesta: se puede integrar
   aunque el usuario esté usando la app. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que BE-5.1 está (desde `BACKEND_FASTAPI/project`; con la imagen anterior el
   segundo da `501`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/localize/frame
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `400` (la ruta existe: sin cuerpo, `400
FOTOS_INVALIDAS`).

4. Mirar la hora, `embedding`, `worker` y la cola `ingesta` (solo lectura):

```bash
export AWS_PROFILE=campus-admin
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_ingesta_url) --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --output text
```

Esperado: antes de las **21:00**; `embedding 1 1` (o `embedding 0 0`: el script lo enciende y al final lo apaga) y
`worker 0 0` o `worker 1 1`; `ingesta` con pocos mensajes (con muchos, el procesado de C1 tarda más; no es un fallo).

**Ejecución.**

5. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate51.py --entorno dev
```

Esperado (5–25 min; el progreso del encendido, si lo hay, sale por stderr): código 0 con `[PASA]` en P1–P5 y en C4,
C1, C2, C3, C6 y C5. P2 termina en `BE-2.2 y BE-4.1 «Hecho» · https://…/v1 · /v1/health/ready → "db": "ok" · HH:MM en
Bogotá`; P3, `login admin 200 (rol admin) · POST /v1/localize/frame sin foto → 400 FOTOS_INVALIDAS`; P4, `red de
tareas y campus-locator-dev-validacion:<n> (SQL de C5)`; P5, `embedding ya encendido (latido publicado) · …` (o
`encendido en N s · …`); `[PREPARACION] sin restos validacion-51-` (o `restos validacion-51- borrados: n`); C4 `sin
metadatos → 422 metadatos · sin posicion_previa → 422 metadatos.posicion_previa · lat 91 → 422
metadatos.posicion_previa.lat · radio_m 500 → 422 metadatos.radio_m · rumbo 360 → 422 metadatos.rumbo · dos fotos →
400 indice 1 · foto PNG → 400 indice 0`; C1 `fotos procesadas en N min · previa a 15 m: ok a 0.x m de A, confianza 1.0
alta, distancia_previa_m 15.0 (real 15.0), imagenes_en_radio 2, latencia_ms …`; C2 `previa en B (300 m de A):
sin_coincidencias, nunca A · imagenes_en_radio 2 (…)` (o `ok a ~300 m de A (en B)`); C3 `previa a 60 m de A: radio_m
30 → sin_coincidencias (0 imágenes) · radio_m 100 → ok a 0.x m de A, distancia_previa_m 60.0 (real 60.0)`; C6 `4
respuestas: latencia_ms mediana …, máxima … (≤ 1000) · …`; C5 `4 filas con origen = frame y fotos_usadas = 1, una por
cada 200 y en orden (ok, sin_coincidencias, sin_coincidencias, ok); ninguna de los errores` (con C2 en B: `ok, ok,
sin_coincidencias, ok`); y al final `[LIMPIEZA] video de prueba borrado (la purga limpia S3) · embedding sigue
encendido (como estaba)` y `== Resultado: pasa (código 0)`. Con eso, el maestro pasa la fila BE-5.1 de PLAN §3 a
«Hecho» con el commit, la fecha y la versión de ARCHITECTURE. **Sin ejecutar todavía**: los números de arriba
(similitudes, latencias) son los esperados, no medidos.

6. Solo si el script se interrumpió y en el paso 4 `embedding` estaba apagado: apagarlo con la herramienta de infra
   (infra §5.11) y comprobarlo:

```bash
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: código 0 y las líneas `embedding 0` y `worker 0`. El video de prueba lo borra la preparación de la siguiente
ejecución.

En `local` no se ejecuta: el script termina con 3 (`BE-5.1 solo admite el entorno: dev`). Lo que sí se comprueba en
`local` está en el paso 1: la petición y la respuesta sin base (`tests/api/test_localizar_frame.py`), el contrato
(`tests/contrato/test_contrato_localizacion.py`), la búsqueda contra PostgreSQL (`tests/base/test_frame_base.py`, en el
CI) y el validador contra un mundo falso con backends defectuosos (`tests/ops/test_validate51.py`).
