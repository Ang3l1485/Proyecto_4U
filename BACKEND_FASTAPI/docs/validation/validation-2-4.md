# Validación 2-4 — BE-2.4 Diagnóstico de búsqueda

| Campo | Valor |
|---|---|
| Lote | `BE-2.4` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate24.py` |
| Entornos | `dev` (necesita S3, SQS, el `worker` y `embedding` para indexar las fotos de prueba; no se emulan en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |
| Hora límite para empezar | **21:00 de Bogotá** (UTC−5): dura 15–40 min y `embedding` se apaga solo a las 22:00 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-2.2 y BE-2.4: `EmbeddingDev`, `pedir_vecinos`, `jpeg_patron`…). Cómo funciona el
endpoint: `ARCHITECTURE.md` §4.8; su contrato, §5.5.

## 1. Precondiciones

Si una no se cumple, el script termina con código 2 (otro lote no está listo) o 3 (credenciales, permisos u hora), sin
crear nada. P5 es la única que cambia algo (enciende `embedding`) y va la última.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | `BE-2.2` en «Hecho», la API con base y dentro de horario | La fila `BE-2.2` de `BACKEND_FASTAPI/docs/PLAN.md` §3 dice `Hecho` (si no: código 2); hora de Bogotá antes de las 21:00 (si no: código 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: código 2) |
| P3 | Login de admin y `BE-2.4` desplegado | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es código 3); `POST /v1/admin/diagnostico/vecinos` con una sola parte `otra` (sin `foto`; no llama a embeddings) → `400 FOTOS_INVALIDAS` (un `404` es código 2: «BE-2.4 sin desplegar») |
| P4 | Recursos para inspeccionar e INF-2.1 | Output `bucket_dataset` y `comprobar_bucket` (como P4 de BE-2.1); outputs `subredes_tareas` y `sg_migrate`; `describe-task-definition` de `campus-locator-dev-validacion`, y las últimas revisiones de `campus-locator-dev-migrate` y `campus-locator-dev-worker` con **la misma imagen** que el servicio `api` (si no: código 2, «BE-2.4 sin desplegar del todo»); objetivos escalables de `embedding` y `worker`, política `campus-locator-dev-worker-cola` y acción `campus-locator-dev-embedding-apagar-noche` (`EmbeddingDev.comprobar_inf21`; si falta: código 2) |
| P5 | `embedding` encendido y visto por `api` | Si `embedding` tiene `desiredCount ≥ 1` y `/v1/health/ready` dice `"embedding": "ok"`: solo publica un latido (`EmbeddingEncendidos`). Si no: lo enciende con el contrato de infra §5.10 (§4) y espera a `"embedding": "ok"`. Anota cómo lo encontró **antes** de encender (la limpieza lo apaga aunque el encendido falle a medias). Si no queda listo: código 2 |

**Preparación** (tras las precondiciones; un fallo solo se avisa, y entonces C4a falla por no tener las lecturas):
1. Si `GET /v1/admin/videos?q=validacion-` (todas las páginas) tiene restos con `nombre` **y** `ref_cliente`
   `validacion-…`, lanza `limpiar-validacion` sin `--video` (`comun.borrar_restos`).
2. Lecturas iniciales de C4a (solo si C4a está incluida): todas las claves del bucket (`s3api list-objects-v2`
   paginado, sin prefijo) y, con la tarea `campus-locator-dev-validacion` (`psql -tAc`), `SELECT (SELECT count(*) FROM
   eventos_localizacion), (SELECT count(*) FROM embeddings WHERE version_vector = 'dinov2-vits14/pp-v1')` → `E|N0`.

Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Crea el video `validacion-24-<AAAAMMDD-HHMMSS>` (3 fotos declaradas, coordenadas `1.0, -100.0`), registra y sube 3 JPEG en color de 1024×768 con patrones distintos (tablero, círculos y figuras; `comun.jpeg_patron` con la semilla de la ejecución) con el flujo de BE-2.1, y lee `GET /v1/admin/videos/{id}` cada 15 s hasta que las 3 estén `procesada` (máx. **20 min**: si `worker` estaba en 0, su subida tarda de 2 a 15 min, infra ADR-INF-15). Envía cada foto, con los mismos bytes, a `POST /v1/admin/diagnostico/vecinos?k=5` | Ninguna foto en `error` (sería `falla` inmediata); `200` en las tres; `version_vector = dinov2-vits14/pp-v1`; el primer vecino es la propia `imagen_id`, con `video_id` = el video de prueba y `similitud` ≥ 0,95; vecinos ordenados de mayor a menor similitud |
| C2a | Publica un latido (`EmbeddingEncendidos`: aleja el apagado por inactividad tras la espera de C1). N = `N0` + las fotos de C1 en `procesada` (sin lecturas iniciales, por ejemplo con `--solo C2`, lo cuenta con la consulta de arriba). Envía con `k=5` una cuarta imagen que no se subió (ruido RGB de 512×384, `comun.jpeg_ruido`) | `200`; `vecinos` tiene `min(5, N)` elementos, con `similitud` de mayor a menor; no se descarta ninguno por `LOC_SIM_MIN` (el detalle anota cuántas similitudes quedan por debajo de 0,55, como evidencia) |
| C2b | La misma cuarta imagen con `k=1` y con `k=50` | `1` (o 0 si N = 0) y `min(50, N)` vecinos, ordenados; el primer `imagen_id` de `k=1` y el de `k=5` coinciden |
| C3a | `k=0`, `k=51` y `k=abc` con una foto válida (otro `jpeg_patron`) | `422 VALIDACION` en los tres, con `detalle.campos` que nombra `k` |
| C3b | Sin parte `foto` (una sola parte `otra`); una parte PNG (`Content-Type: image/png`); un JPEG de 1 677 722 bytes (1,6 MiB: `jpeg_sintetico` de 64×48 seguido de ceros, `comun.jpeg_relleno`) | `400 FOTOS_INVALIDAS` en los tres, con `detalle.indice = 0` |
| C3c | Crea o reactiva `validacion+user@campus.edu.co` (§4), inicia sesión con él y llama al endpoint con una foto válida; repite sin encabezado `Authorization` | `403 SIN_PERMISOS` con el token `user` y `401 NO_AUTENTICADO` sin token |
| C4a | Repite las lecturas de la preparación (claves del bucket y la consulta `E\|N`) | Las claves nuevas están todas bajo `dataset/<video de prueba>/` y `thumbs/<video de prueba>/` (las tres fotos de C1 y sus miniaturas: 6); `eventos_localizacion` no cambió; los vectores pasaron de `N0` a `N0` + las fotos de C1 procesadas (+3) |
| C4b | `logs filter-log-events` (sin patrón, todas las páginas) de `/campus-locator/dev/api` y `/campus-locator/dev/embedding` desde 60 s antes de P2 | Ningún evento contiene `/9j/` (comienzo de un JPEG en base64) ni pesa más de 16 KB (16 384 bytes) |

Orden de ejecución: preparación (lecturas iniciales), C1, C2, C3, C4a (lecturas finales), C4b. Cada comprobación
prepara lo que le falta si se ejecuta sola con `--solo` (p. ej. `--solo C1` crea el video y espera las fotos; `--solo
C2` no crea nada y cuenta N con una tarea). C4a supone que nadie sube fotos ni localiza en `dev` mientras corre; si un
conteo no cuadra, el detalle muestra los dos valores para descartar actividad ajena antes de repetir. C2 no usa `GET
/v1/admin/stats` (BE-2.3, que no es dependencia de este lote). El script nunca imprime URLs prefirmadas, tokens ni
contraseñas.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea el video `validacion-24-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 3 JPEG sintéticos (semilla distinta en
cada ejecución) en una coordenada fuera del campus; sus `PUT` generan 3 eventos en `ingesta`, que consume el `worker`.
Usa el usuario `validacion+user@campus.edu.co`, que crea o reactiva con `crear-usuario --rol user` (contraseña
aleatoria en `CREAR_USUARIO_PASSWORD`, nunca impresa) en una tarea suelta de `migrate`. Las fotos de C2 y C3 no se
suben a ningún sitio. Lanza 5 tareas sueltas: 2 de `campus-locator-dev-validacion` (las lecturas de la preparación y
de C4a), 2 de `campus-locator-dev-migrate` (`crear-usuario` y `desactivar-usuario`) y 1 de
`campus-locator-dev-worker` (`limpiar-validacion` al final), y otra de `worker` al empezar si había restos.

**`embedding`** (infra §5.10 y §5.11; `comun.EmbeddingDev.encender`, el mismo contrato que `embedding.py encender` de
infra): 1) `RegisterScalableTarget` 0-1 de `embedding` y `worker`; 2) `PutMetricData` de `EmbeddingEncendidos` = 1 en
`campus-locator/dev`; 3) espera a que `GetMetricStatistics` la devuelva, un minuto más y que la alarma
`campus-locator-dev-embedding-inactivo` no esté en `ALARM` (hasta 5 min); 4) `UpdateService` de `embedding` a 1;
5) espera tarea `HEALTHY`, despliegue `COMPLETED` y esa tarea registrada en Cloud Map (`servicediscovery
list-instances` con su IP privada, ARCHITECTURE §5.11 «Trampa del arranque») (hasta 10 min desde el paso 1) y,
además, `"embedding": "ok"` en `/v1/health/ready` (hasta 2 min). Cuesta ~0,10 USD/h mientras está encendido.

Limpieza (siempre, también si algo falló; **no** con `--sin-limpieza`, que deja también `embedding` como esté y el
usuario activo), en este orden; un fallo en un paso no impide los siguientes:
1. Deja `embedding` como lo encontró: si lo encendió el script (P5), lo apaga como `embedding.py apagar` (rango 0-0 y
   `desiredCount = 0` de `embedding` y `worker`; no espera a que paren); si estaba encendido y quedó en 0, lo vuelve a
   encender con el contrato. Imprime `embedding apagado (lo encendió el validador)`, `embedding sigue encendido (como
   estaba)` o `embedding vuelto a encender (estaba encendido)`; si no lo consigue, `… embedding NO quedó como estaba
   …` (entonces, paso 7 de §5).
2. Borra su video con `limpiar-validacion --video <id>` (tarea suelta con `campus-locator-dev-worker`, ARCHITECTURE
   §5.11; con `DELETE /v1/admin/videos/{id}` cuando BE-4.1 esté «Hecho»): filas (en cascada fotos y vectores) y
   objetos de `dataset/` y `thumbs/`.
3. Si C3c llegó a lanzar `crear-usuario`, desactiva el usuario con `desactivar-usuario` (tarea de `migrate`).

Si el script se interrumpe (Ctrl+C, terminal cerrada): `embedding` puede quedar encendido hasta las 22:00 o hasta 45
min sin uso (paso 7 de §5); el video lo borra la preparación de la siguiente ejecución; el usuario de prueba puede
quedar activo con una contraseña aleatoria que nadie conoce, y lo desactiva la siguiente ejecución de este validador
(o de `validate13.py`).

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`). Necesita leer el secreto `admin-inicial`; `head-bucket`, `head-object` y `list-objects-v2` (sin prefijo) en el bucket del dataset; `ecs run-task`/`describe-*` en `campus-locator-dev` con `iam:PassRole` de los roles de `validacion`, `migrate` y `worker`; `logs:GetLogEvents` en `/campus-locator/dev/validacion`, `…/migrate` y `…/worker`; `logs:FilterLogEvents` en `/campus-locator/dev/api` y `…/embedding`; y, para el encendido, `application-autoscaling:Describe*` y `RegisterScalableTarget`, `cloudwatch:PutMetricData`, `GetMetricStatistics` y `DescribeAlarms`, `ecs:UpdateService`, `ListTasks` y `DescribeTasks`, y `servicediscovery:ListInstances` (con `campus-admin`, todo) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`. El
informe queda en `project/.validacion/BE-2.4-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe RUTA`. Recursos
compartidos (los coordina el maestro): mientras corre, nadie más enciende o apaga `embedding`, cambia `desiredCount` de
`worker`, deja mensajes en `ingesta`, sube fotos o llama a `POST /v1/localize` en `dev`, ni hace push a `main` con
cambios en `BACKEND_FASTAPI/project/**` o `SERVICE_EMBEDDING/project/**`.

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

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
`migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker`. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que el endpoint existe (desde `BACKEND_FASTAPI/project`; sin token, `401`;
con la imagen anterior a BE-2.4, `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/admin/diagnostico/vecinos
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `401`.

4. Comprobar que las revisiones de `migrate` y `worker` llevan la misma imagen que `api` (si no, P4 termina con 2):

```bash
export AWS_PROFILE=campus-admin
aws ecs describe-task-definition --task-definition campus-locator-dev-migrate --query 'taskDefinition.containerDefinitions[0].image' --output text
aws ecs describe-task-definition --task-definition campus-locator-dev-worker --query 'taskDefinition.containerDefinitions[0].image' --output text
aws ecs describe-task-definition --task-definition $(aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].taskDefinition' --output text) --query 'taskDefinition.containerDefinitions[0].image' --output text
```

Esperado: tres líneas iguales, `…/campus-locator/backend:<SHA del commit>`.

5. Mirar la hora y el estado de `embedding` y `worker` (solo lectura):

```bash
TZ=America/Bogota date +%H:%M
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount,runningCount]' --output text
```

Esperado: una hora **antes de las 21:00**; `embedding 0 0` y `worker 0 0` (apagados: el script los enciende y al
final los apaga) o `embedding 1 1` (encendido: lo deja encendido).

**Ejecución.**

6. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate24.py --entorno dev
```

Esperado (15–40 min; el progreso del encendido sale por stderr): código 0, con `[PASA]` en P1–P5 y en C1, C2a, C2b,
C3a, C3b, C3c, C4a y C4b. P2 termina en `… /v1/health/ready → "db": "ok" · HH:MM en Bogotá (antes de las 21:00)`; P3
en `login admin 200 (rol admin) · POST /v1/admin/diagnostico/vecinos sin foto → 400 FOTOS_INVALIDAS`; P5 en
`embedding encendido en N s · /v1/health/ready → "embedding": "ok"` (o `embedding ya encendido (latido publicado) ·
…`); antes de C1, `[PREPARACION] sin restos validacion- de ejecuciones anteriores · lecturas iniciales: <n> objetos en
S3, eventos_localizacion = <E>, <N0> vectores dinov2-vits14/pp-v1`; C1 `video <id>: fotos 1–3 en procesada en N min ·
cada una es su primer vecino (similitud 0.9xxx, 0.9xxx, 0.9xxx) · version_vector = dinov2-vits14/pp-v1`; C2a `N =
<N0+3> vectores en el índice · k=5 → <min(5, N)> vecinos ordenados (similitud a–b; n por debajo de LOC_SIM_MIN = 0.55,
no se descartan)`; C2b `k=1 → 1 y k=50 → <min(50, N)> vecinos (N = …), ordenados; k=1 y k=5 empiezan igual`; C3a
`k=0, k=51 y k=abc → 422 VALIDACION con detalle.campos = [k]`; C3b `sin parte foto, parte PNG y JPEG de 1,6 MB → 400
FOTOS_INVALIDAS con detalle.indice = 0`; C3c `token de validacion+user@campus.edu.co → 403 SIN_PERMISOS · sin token →
401 NO_AUTENTICADO`; C4a `6 claves nuevas, todas de dataset/ y thumbs/ del video de prueba · eventos_localizacion =
<E>, sin cambios · vectores <N0> → <N0+3> (+3: las fotos de C1)`; C4b `eventos desde el inicio: <n> en api y <m> en
embedding; ninguno con /9j/ ni de más de 16 KB`; y al final `[LIMPIEZA] embedding apagado (lo encendió el validador) ·
videos de prueba borrados: {"videos": 1, "objetos": 6} · validacion+user@campus.edu.co desactivado` (o `embedding
sigue encendido (como estaba) · …`). Con eso, el maestro pasa la fila BE-2.4 de PLAN §3 a «Hecho» con el commit, la
fecha y la versión de ARCHITECTURE.

7. Solo si el script se interrumpió (o la limpieza dijo `embedding NO quedó como estaba`) y en el paso 5 `embedding`
estaba apagado: apagarlo con la herramienta de infra (infra §5.11) y comprobarlo:

```bash
cd ../../INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/embedding.py apagar
aws ecs describe-services --cluster campus-locator-dev --services embedding worker --query 'services[].[serviceName,desiredCount]' --output text
```

Esperado: código 0 y las líneas `embedding 0` y `worker 0`. Los restos del video los borra la preparación de la
siguiente ejecución.

En `local` no se ejecuta (S3, SQS y el `worker` no se emulan): el script termina con 3 (`BE-2.4 solo admite el
entorno: dev`). Lo que sí se comprueba en `local` está en las pruebas del paso 1: el endpoint con PostgreSQL real y
embeddings simulado (`tests/base/test_diagnostico_base.py` cubre C1–C4 sin S3), el multipart
(`tests/unit/test_multipart.py`), el contrato (`tests/contrato/test_contrato_diagnostico.py`) y el validador contra un
mundo falso con interruptores de backend defectuoso (`tests/ops/test_validate24.py`).
