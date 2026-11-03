# Validación 3-2 — BE-3.2 Localización

| Campo | Valor |
|---|---|
| Lote | `BE-3.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate32.py` |
| Entornos | `dev` (necesita el dataset real indexado, el conjunto de `evaluacion/` en S3 y `embedding`; no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4 (C4a, C4b, C4c), C5, C6 · Manuales: ninguno |
| Hora límite para empezar | **21:00 de Bogotá** (UTC−5): dura 10–25 min y `embedding` se apaga solo a las 22:00 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de `comun.py` y «`validate32.py`»). Cómo funciona el endpoint: `ARCHITECTURE.md`
§4.10; su contrato, §5.3. El conjunto de consulta lo define `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5.9 (EMB-3.2).

**Estado (2026-10-25):** el script existe y está probado contra un mundo falso (`tests/ops/test_validate32.py`), pero
**no se ha ejecutado en `dev`**: faltan el dataset real (FE-2.1), el conjunto de EMB-3.2 y la calibración. Mientras
§5.10 diga «Iniciales», C6 falla a propósito.

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, herramientas,
permisos u hora), sin localizar nada. P6 es la única que cambia algo (enciende `embedding`) y va la última.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` y, si C4c está incluida, `aws` y el *Session Manager plugin* | `sts get-caller-identity` → `Account` (si falla: 3); `aws` y `session-manager-plugin` en el `PATH` (si falta alguno: 3; con `--solo` sin C4c no se mira) |
| P2 | `BE-2.2`, `BE-2.4` y `BE-3.1` en «Hecho», dentro de horario y la API con base | Sus filas de `BACKEND_FASTAPI/docs/PLAN.md` §3 dicen `Hecho` (si no: 2); hora de Bogotá antes de las 21:00 (si no: 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: 2) |
| P3 | `BE-3.2` desplegado, lugares y ECS Exec | `POST /v1/localize` con una sola parte `otra` (sin `fotos`: no llama a embeddings ni escribe evento) → `400 FOTOS_INVALIDAS` (un `404` es 2: «BE-3.2 sin desplegar»); `GET /v1/places` → `200` (anota el `total`; si no: 2); si C4c está incluida, `ecs describe-services --services api` → `enableExecuteCommand = true` (si no: 2, INF-1.3) |
| P4 | `EMB-3.1` y `EMB-3.2` en «Hecho» y el conjunto de consulta publicado | Sus filas de `SERVICE_EMBEDDING/docs/PLAN.md` §3 dicen `Hecho` (si no: 2); `s3api list-objects-v2 --bucket <bucket_dataset> --prefix evaluacion/ --delimiter /` → la última `<version_conjunto>` con la forma `AAAA-MM<letra>` (orden lexicográfico; las demás carpetas se ignoran); su `puntos.json` (embeddings §5.9; si falta o no tiene esa forma: 2) con ≥ 10 puntos que tengan alguna foto en S3 (`list-objects-v2` de `evaluacion/<versión>/fotos/`; si no: 2). Sin permiso de lectura: 3 |
| P5 | Dataset real del campus (`FE-2.1` en «Hecho») | La fila FE-2.1 de `FRONTEND_KOTLIN/docs/PLAN.md` §3 dice `Hecho` (si no: 2); outputs `subredes_tareas` y `sg_migrate` y la definición `campus-locator-dev-validacion` (si no: 2); con la tarea de validación (`psql -tAc`) `SQL_DATASET`: `SELECT DISTINCT round(i.lat::numeric, 5), round(i.lng::numeric, 5) FROM imagenes i JOIN videos v ON v.id = i.video_id JOIN embeddings e ON e.imagen_id = i.id WHERE e.version_vector = 'dinov2-vits14/pp-v1' AND i.estado = 'procesada' AND v.estado <> 'eliminado' AND v.nombre NOT LIKE 'validacion-%'` → al menos una posición (si no: 2). Con esas posiciones clasifica cada punto: **con dataset** (alguna a ≤ 30 m), **fuera de cobertura** (todas a más de 150 m) o intermedio (no se consulta) |
| P6 | `embedding` encendido y visto por `api` | Como P5 de `validation-2-4.md`: si `embedding` tiene `desiredCount ≥ 1` y `/v1/health/ready` dice `"embedding": "ok"`, solo publica un latido; si no, lo enciende con el contrato de infra §5.10 (§4) y espera a `"embedding": "ok"`. Anota cómo lo encontró **antes** de encender. Si no queda listo: 2. Con `--solo` sin C1, C2, C3, C4a ni C5 no hace nada («no hace falta») |

No hay preparación: el validador no crea datos de prueba ni hay restos que borrar al empezar.

## 2. Comprobaciones automáticas

Cada localización es un `POST /v1/localize` con hasta 5 fotos del punto (las primeras en el orden de `puntos.json`,
reducidas como la app: orientación EXIF aplicada, lado mayor 1024 px, JPEG calidad 85, sin EXIF) y `metadatos` =
`{"rumbos": [<de puntos.json o null>…], "origen": "escaneo", "app_version": "validacion-32"}`; error = haversine
(R = 6 371 008,8 m) entre `posicion` y la coordenada del punto; `sin_coincidencias` cuenta como error infinito. Las
peticiones van de una en una (como una persona que escanea). Una respuesta que no sea `200` hace fallar la comprobación
que la envió.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Una localización por cada punto con dataset (P5) | ≥ 10 puntos con dataset y error mediano ≤ 15 m (el detalle añade el p90, los niveles y cuántas respuestas traen `lugar_cercano`) |
| C3 | Comprueba `embedding` (`describe-services` → `runningCount = 1`; `describe-task-definition` de su `taskDefinition` → `cpu = "2048"`, `memory = "4096"`) y que `ingesta` tiene 0 mensajes visibles y en vuelo; hace 3 localizaciones de calentamiento (no cuentan) y 100 medidas recorriendo los puntos con dataset que tienen 5 fotos, anotando el encabezado `apigw-requestid` de cada respuesta; 2 min después lee de `/campus-locator/dev/apigw` (`logs filter-log-events` sin patrón, desde 60 s antes de la primera medida; hasta 3 lecturas más, cada 30 s, si faltan líneas) el `integrationLatency` de esas 100 | Las 100 dan `200` con un `apigw-requestid` distinto cada una, sus 100 líneas de *access log* están y el p95 de `integrationLatency` (rango más cercano: el valor 95 de los 100 ordenados) es ≤ 1 000 ms (infra §5.10). El detalle añade el p50, la mediana de `latencia_ms` de la API y el p95 medido en el cliente (con la red de quien valida; no cuenta) |
| C5 | Una localización por cada punto fuera de cobertura (P5) | Hay al menos uno (si no, falla con «conjunto sin puntos fuera de cobertura») y todos dan `200` con `resultado = "sin_coincidencias"`, `confianza = 0` y `posicion = null` |
| C2 | Revisa las respuestas de C1 y de las 100 medidas de C3 con `nivel = "alta"` (si se ejecuta sola con `--solo`, antes hace las de C1 y C3) | Ninguna con error > 30 m |
| C4a | Calcula el MD5 de cada foto enviada (C1, C3 con el calentamiento, y C5; si no se envió ninguna, las de C1) y lista todo el bucket (`list-objects-v2` paginado, sin prefijo) | Ningún `ETag` coincide con esos MD5 |
| C4b | `logs filter-log-events` (sin patrón, todas las páginas) de `/campus-locator/dev/api`, `/campus-locator/dev/apigw` y `/campus-locator/dev/embedding` desde 60 s antes de P2 | Ningún evento contiene `/9j/` (comienzo de un JPEG en base64) ni pesa más de 16 KB (16 384 bytes) |
| C4c | `ecs list-tasks --service-name api` y, por cada tarea, `aws ecs execute-command --cluster campus-locator-dev --task <tarea> --container app --interactive --command "find / -xdev -type f -newermt @<epoch del inicio de P2> -size +50k"` | Ninguna línea de la salida que empiece por `/` (los mensajes de la sesión y los `find: … Permission denied` no cuentan), salvo las de `/var/log/amazon/` (logs del agente de ECS Exec; a verificar en la primera ejecución) |
| C6 | Lee `docs/ARCHITECTURE.md` y `docs/CHANGELOG.md` de la copia local | En §5.10 las filas de `LOC_SIM_MIN / LOC_SIM_ALTA` y de los cortes de nivel ya no dicen «Iniciales»; la versión del encabezado es posterior a 0.12.0 (la que construyó BE-3.2 sin calibrar) y una entrada del CHANGELOG posterior a 0.12.0 tiene «Lote que la motivó» con BE-3.2 y habla de la calibración («calibr») |

Orden de ejecución: C1, C3, C5, C2, C4a, C4b, C4c, C6 (C2 necesita las respuestas de C1 y C3, y C4a todas las fotos
enviadas). Cada comprobación prepara lo que le falta si se ejecuta sola con `--solo` (`--solo C2` hace las peticiones de
C1 y C3; `--solo C4` localiza los puntos de C1 para tener algo que buscar). C3 falla si `ingesta` tiene mensajes: el
`worker` competiría por `embedding` y la medida no valdría (esperar a que se vacíe). El script nunca imprime tokens ni
URLs prefirmadas (no usa ninguna).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos de prueba en la API ni en el bucket, y nunca escribe en `evaluacion/`. Cada localización deja una fila
anónima en `eventos_localizacion` (116 en una ejecución completa con 12 puntos con dataset y uno lejano: 12 de C1, 3 + 100
de C3 y 1 de C5), reconocibles por `app_version = "validacion-32"`; no hay endpoint para borrarlas y caducan a los 180
días (`EVENTOS_RETENCION_DIAS`). Las fotos del conjunto se descargan y reducen **en memoria** (nada en disco) y se
descartan al terminar. Lanza 1 tarea suelta de `campus-locator-dev-validacion` (`SQL_DATASET`, P5) y, en C4c, una sesión
de ECS Exec por tarea de `api`.

**`embedding`** (infra §5.10 y §5.11; `comun.EmbeddingDev.encender`, el mismo contrato que `embedding.py encender` de
infra): 1) `RegisterScalableTarget` 0-1 de `embedding` y `worker`; 2) `PutMetricData` de `EmbeddingEncendidos` = 1 en
`campus-locator/dev`; 3) espera a que `GetMetricStatistics` la devuelva, un minuto más y que la alarma
`campus-locator-dev-embedding-inactivo` no esté en `ALARM` (hasta 5 min); 4) `UpdateService` de `embedding` a 1;
5) espera tarea `HEALTHY`, despliegue `COMPLETED` y esa tarea registrada en Cloud Map (`servicediscovery list-instances`
con su IP privada) (hasta 10 min desde el paso 1) y, además, `"embedding": "ok"` en `/v1/health/ready` (hasta 2 min).
Las localizaciones mantienen alejado el apagado por inactividad. Cuesta ~0,10 USD/h mientras está encendido.

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`, que deja `embedding` como esté): deja `embedding`
como lo encontró (si lo encendió el script, lo apaga como `embedding.py apagar`: rango 0-0 y `desiredCount = 0` de
`embedding` y `worker`, sin esperar; si estaba encendido y quedó en 0, lo vuelve a encender) y descarta las fotos de la
memoria. Imprime `embedding apagado (lo encendió el validador)`, `embedding sigue encendido (como estaba)` o `embedding
vuelto a encender (estaba encendido)`; si no lo consigue, `embedding NO quedó como estaba …` (entonces, paso 8 de §5).
Si el script se interrumpe (Ctrl+C, terminal cerrada), `embedding` puede quedar encendido hasta las 22:00 o hasta 45 min
sin uso (paso 8).

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Necesita `s3:ListBucket` en el bucket del dataset (sin prefijo, para C4a, y en `evaluacion/`) y `s3:GetObject` en `evaluacion/*`; `ecs run-task`/`describe-*`/`list-tasks` en `campus-locator-dev` con `iam:PassRole` del rol de la tarea de validación, `ecs:ExecuteCommand` en las tareas de `api` (y `ssm:StartSession` para la sesión); `logs:GetLogEvents` en `/campus-locator/dev/validacion`; `logs:FilterLogEvents` en `/campus-locator/dev/api`, `…/apigw` y `…/embedding`; `sqs:GetQueueAttributes` en `ingesta`; y, para el encendido, `application-autoscaling:Describe*` y `RegisterScalableTarget`, `cloudwatch:PutMetricData`, `GetMetricStatistics` y `DescribeAlarms`, `ecs:UpdateService` y `servicediscovery:ListInstances` (con `campus-admin`, todo) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |

No usa credenciales de admin. Herramientas: `terraform` con `terraform init` hecho en
`INFRASTRUCTURA_TERRAFORM/project/envs/dev`, `uv`, la CLI `aws` y el *Session Manager plugin* (C4c). El informe queda
en `project/.validacion/BE-3.2-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe RUTA`. Recursos compartidos (los
coordina el maestro): mientras corre, nadie más enciende o apaga `embedding`, cambia `desiredCount` de `worker`, deja
mensajes en `ingesta`, sube fotos o llama a `POST /v1/localize` en `dev`, ni hace push a `main` con cambios en
`BACKEND_FASTAPI/project/**` o `SERVICE_EMBEDDING/project/**`.

**Preparación en `dev`** (en WSL, desde la raíz del monorepo). Antes de todo: FE-2.1 y EMB-3.2 en «Hecho» (dataset real
indexado y conjunto subido) y la calibración hecha (ARCHITECTURE §4.10, «Calibración»; sin ella, C6 falla).

1. Pruebas y estilo en la máquina, con el PostgreSQL del compose para las pruebas `base`:

```bash
cd BACKEND_FASTAPI/project
docker compose up -d --wait db
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `… files already formatted` y `… passed` sin fallos ni omitidas.

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
`migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker`. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que el endpoint existe (desde `BACKEND_FASTAPI/project`; un cuerpo vacío no
es multipart, así que no llama a embeddings ni escribe evento; con la imagen anterior a BE-3.2, `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/localize
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `400`.

4. Comprobar el conjunto de EMB-3.2 en S3 (solo lectura):

```bash
export AWS_PROFILE=campus-admin
aws s3 ls s3://campus-locator-dev-dataset-648617469176/evaluacion/
```

Esperado: una línea `PRE <AAAA-MM><letra>/` por versión (`PRE 2026-11a/`…); el script usa la última en orden
lexicográfico.

5. Comprobar el *Session Manager plugin* y que `api` tiene ECS Exec:

```bash
session-manager-plugin --version
aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].enableExecuteCommand' --output text
```

Esperado: un número de versión (p. ej. `1.2.707.0`) y `True`. Si falta el plugin, instalarlo una vez (Ubuntu en WSL,
paquete oficial de AWS) y repetir:

```bash
curl -sSo /tmp/session-manager-plugin.deb https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb
dpkg -i /tmp/session-manager-plugin.deb
```

6. Mirar la hora, el estado de `embedding` y `worker` y la cola `ingesta` (solo lectura):

```bash
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
aws sqs get-queue-attributes --queue-url $(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw sqs_ingesta_url) --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query 'Attributes' --output text
```

Esperado: una hora **antes de las 21:00**; `embedding 0 0` y `worker 0 0` (apagados: el script los enciende y al final
los apaga) o `embedding 1 1` (encendido: lo deja encendido); y dos ceros en la cola (visibles y en vuelo; si no,
esperar a que el `worker` la vacíe, o C3 fallará).

**Ejecución.**

7. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate32.py --entorno dev
```

Esperado (10–25 min; el progreso del encendido sale por stderr): código 0, con `[PASA]` en P1–P6 y en C1, C3, C5, C2,
C4a, C4b, C4c y C6. P1 termina en `… · aws y session-manager-plugin en el PATH`; P2 en `BE-2.2, BE-2.4 y BE-3.1
«Hecho» · <URL> · /v1/health/ready → "db": "ok" · HH:MM en Bogotá (antes de las 21:00)`; P3 en `POST /v1/localize sin
fotos → 400 FOTOS_INVALIDAS · GET /v1/places → 200 (<n> lugares) · api con ECS Exec`; P4 en `EMB-3.1 y EMB-3.2
«Hecho» · conjunto <versión>: <p> puntos, <f> fotos`; P5 en `FE-2.1 «Hecho» · <n> posiciones indexadas · puntos con
dataset (≤ 30 m): <c> · fuera de cobertura (> 150 m): <l> · intermedios: <i>`; P6 en `embedding encendido en N s ·
/v1/health/ready → "embedding": "ok"` (o `embedding ya encendido (latido publicado) · …`); C1 `<c> puntos con dataset ·
error mediano <e> m (máx. 15) · p90 … · alta/media/baja/sin_coincidencias = … · con lugar_cercano: …`; C3 `embedding
2048/4096 con 1 tarea · ingesta vacía · 100 × 200 · integrationLatency p50 … ms, p95 … ms (máx. 1000) · …`; C5 `<l>
puntos fuera de cobertura → 200 sin_coincidencias, confianza 0 y posicion null`; C2 `<a> respuestas de nivel alta (de
<c + 100>: C1 y C3) · error máximo … m (máx. 30)`; C4a `<n> fotos enviadas · <m> objetos en el bucket · ningún ETag
coincide`; C4b `eventos desde el inicio: … en api, … en apigw, … en embedding; ninguno con /9j/ ni de más de 16 KB`; C4c
`1 tarea(s) de api: \`find / -xdev -type f -newermt @… -size +50k\` sin archivos (salvo /var/log/amazon/)`; C6 `§5.10
sin «Iniciales» · ARCHITECTURE <versión> · CHANGELOG <versión> (BE-3.2)`; y al final `[LIMPIEZA] embedding apagado (lo
encendió el validador) · <n> fotos del conjunto descartadas de la memoria · <k> localizaciones medidas (filas
app_version = validacion-32)` (o `embedding sigue encendido (como estaba) · …`). Con eso, el maestro pasa la fila
BE-3.2 de PLAN §3 a «Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

8. Solo si el script se interrumpió (o la limpieza dijo `embedding NO quedó como estaba`) y en el paso 6 `embedding`
estaba apagado: apagarlo con la herramienta de infra (infra §5.11) y comprobarlo:

```bash
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: código 0 y las líneas `embedding 0` y `worker 0`.

En `local` no se ejecuta (el dataset real, S3, `embedding` y ECS Exec no se emulan): el script termina con 3 (`BE-3.2
solo admite el entorno: dev`). Lo que sí se comprueba en `local` está en las pruebas del paso 1: el algoritmo
(`tests/unit/test_localizacion.py`), el endpoint con PostgreSQL real y embeddings simulado
(`tests/base/test_localizacion_base.py`: posición, contexto, `sin_coincidencias`, errores y C4 sin S3), el contrato
(`tests/contrato/test_contrato_localizacion.py`) y el validador contra un mundo falso con interruptores de backend
defectuoso (`tests/ops/test_validate32.py`).
