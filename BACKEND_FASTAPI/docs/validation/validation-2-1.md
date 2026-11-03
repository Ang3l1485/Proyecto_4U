# Validación 2-1 — BE-2.1 Recolección (subida del dataset)

| Campo | Valor |
|---|---|
| Lote | `BE-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `dev` (necesita S3, que no se emula en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (o con 3 si es un problema de
credenciales o configuración).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | URL de la API | `VALIDACION_API_URL`, o el output `api_base_url` (`terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -json`) + `/v1`; `GET /v1/health` → `200` (informa el `commit`) |
| P3 | `BE-1.3` en «Hecho»: login de admin | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"`. Un `401` es código 3 (credenciales que no valen) |
| P4 | Bucket del dataset accesible con los permisos que usan las comprobaciones | Output `bucket_dataset`; `head-bucket`, `list-objects-v2 --prefix dataset/ --max-keys 1` y `head-object` de una clave que no existe (`dataset/validacion-sonda-<uuid>.jpg`, 404 esperado) (`comun.comprobar_bucket`). Bucket inexistente: código 2; cualquier permiso que falte: código 3, antes de crear nada. Mide además el desfase del reloj local con el `Date` de S3 (lo informa: `reloj local +N s respecto a S3`) |
| P5 | Definición `campus-locator-dev-worker` con la **misma imagen** que el servicio `api` (BE-2.1 desplegado del todo) y red de las tareas sueltas (INF-1.3, INF-1.1) | `EntornoBackend.revision(FAMILIA_WORKER)` (compara la imagen de la última revisión de `worker` con la del servicio `api`) y los outputs `subredes_tareas` y `sg_migrate`. Imágenes distintas o definición inexistente: código 2, antes de crear nada |

**Preparación** (tras las precondiciones, antes de C1; un fallo solo se avisa): recorre todas las páginas de
`GET /v1/admin/videos?q=validacion-` y, si hay videos cuyo `nombre` **y** `ref_cliente` empiezan por `validacion-` (el
mismo criterio que la CLI: restos de una ejecución interrumpida), lanza `limpiar-validacion` **sin** `--video` con la
definición de `worker` (`comun.borrar_restos`). Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `POST /v1/collect/videos` con el cuerpo de §5.4, `ref_cliente` y `nombre` = `validacion-21-<AAAAMMDD-HHMMSS>`, `total_fotos: 4` y coordenadas fuera del campus (`1.0, -100.0`) | `201` con un `VideoResumen` (exactamente los campos de §5.5) en `estado = "pendiente"`, ese `nombre` y ese `ref_cliente`, `total_fotos = 4`, conteo en 0 y `creado_por.id` = el admin de P3 |
| C1b | `POST /v1/collect/videos/{id}/images` con 4 elementos (`orden` 1–4, `rumbo` 0/90/180/270, `bytes` = tamaño real) y `PUT` de las fotos 1–3 a `subida.url` enviando exactamente `subida.encabezados` | Las 4 en `pendiente_subida` con ids distintos, `subida.metodo = "PUT"`, `encabezados = {"Content-Type": "image/jpeg"}`, URL `https://` y `expira_en` en el futuro (con la hora de S3); los tres `PUT` dan `200` |
| C1c | `s3api head-object --bucket campus-locator-dev-dataset-648617469176 --key dataset/{video_id}/{imagen_id}.jpg` de las fotos 1–3 | Existen, con `ContentType = image/jpeg` y `ContentLength` igual a los bytes enviados |
| C2a | Repite `POST /v1/collect/videos` con el mismo cuerpo | `200` con el mismo `id` y el mismo `numero` |
| C2b | Repite `POST …/images` con los 4 elementos | Mismo `id` para cada `orden`; fotos 1–3 con `subida = null` y un estado distinto de `pendiente_subida` (`subida` por el `HEAD` de §4.5, o posterior si el `worker` ya las procesó); foto 4 con `subida` no nula |
| C2c | Repite el `PUT` de la foto 1 (misma URL de C1b y mismo cuerpo); `s3api list-objects-v2 --prefix dataset/{video_id}/` | El `PUT` da `200` y hay exactamente 3 objetos |
| C3a | Con la URL de la foto 4 obtenida en C1b, espera a que pase su `expira_en` (`PRESIGN_PUT_TTL_S` = 900 s) más 10 s **según la hora de S3** (reloj local + desfase de P4, que vuelve a medir justo antes del `PUT`) y hace el `PUT` | `403` de S3 con `<Code>AccessDenied</Code>` y el mensaje `Request has expired`. Un `200` es `falla` («S3 aún no la daba por vencida»; la foto 4 quedaría subida y C3b también fallaría) |
| C3b | `POST …/images` solo con el elemento `orden: 4`; `PUT` con la URL nueva; `head-object` de su clave | Mismo `id`, `expira_en` en el futuro, `PUT` `200` y el objeto existe |
| C4 | Justo después de los `PUT` (sin esperar al `worker`), `POST /v1/collect/videos/{id}/complete` dos veces | `200` las dos; cuerpo con exactamente `id`, `estado` y `conteo`; `conteo` con exactamente `pendiente_subida`, `subida`, `procesada` y `error`, que suman 4, con `pendiente_subida = 0` (el `HEAD` de `complete` marca `subida` lo que ya está en S3, §4.5); la segunda con el mismo `id` y la misma suma; en las dos, `estado` = el que §5.5 deriva de ese conteo (`procesando` si queda alguna `subida`; si no, `con_errores` o `procesado`). Con el `worker` apagado: `subida = 4` y `estado = "procesando"` |
| C5 | `GET /v1/admin/videos/{id}` y `GET /v1/admin/videos?q=<nombre del video>` | El detalle tiene los campos de `VideoResumen` más `fotos`, en orden 1–4, cada una con los campos de `ImagenAdmin` y su `video_id`; su `conteo` es el de la segunda respuesta de C4 (o difiere solo en fotos `subida` que el `worker` pasó a `procesada` o `error`); el listado lo incluye |
| C6a | Crea un segundo video `validacion-21-<ts>-b` con 1 foto subida y lanza `limpiar-validacion --video <id>` con la definición `campus-locator-dev-worker`; luego `GET /v1/admin/videos/{id}` y `s3api list-objects-v2 --prefix dataset/{id}/` | La tarea sale con 0 y su log tiene `LIMPIEZA {"videos": 1, "objetos": m}` con `m` ≥ 1 (el log se relee, hasta ~1 min, mientras no llegue esa línea: `comun.fin_limpieza`); el `GET` da `404 NO_ENCONTRADO` y no quedan objetos |
| C6b | Lanza `limpiar-validacion --video <uuid inexistente>` y, si `GET /v1/admin/videos` (todas las páginas) muestra algún video sin el prefijo `validacion-` en `nombre` o en `ref_cliente` (por ejemplo, del dataset real), `limpiar-validacion --video <su id> --simular` (la orden real **nunca** se apunta a un video ajeno: `--simular` hace las mismas comprobaciones sin borrar nada) | Las dos tareas salen con 1 y con el evento `limpieza_rechazada` en su log, y ese video sigue existiendo (`GET /v1/admin/videos/{id}` → `200`). Sin videos así, solo se comprueba la primera |

Orden de ejecución: C1, C2, C3, C4, C5, C6 (la espera de C3a es casi toda la duración). Cada comprobación prepara lo
que le falta si se ejecuta sola con `--solo` (p. ej. `--solo C4` crea el video, registra y sube las 4 fotos con URLs
nuevas, sin esperar a que venza ninguna). El script nunca imprime las URLs prefirmadas: solo el código de estado de
cada `PUT`.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea un video `validacion-21-<AAAAMMDD-HHMMSS>` (mismo valor en `ref_cliente` y `nombre`, único por ejecución) con 4
JPEG sintéticos de 1024×768 (`comun.jpeg_sintetico`, ~12 KB cada uno, semilla distinta en cada ejecución) y
coordenadas fuera del campus, y el video `-b` de C6a. Como `ref_cliente` es único por ejecución, los restos no
interfieren con la idempotencia que mide C2.

Limpieza (backend `ARCHITECTURE.md` §5.11): al terminar, también si algo falló, borra los videos que creó y que aún
existen con `limpiar-validacion --video <id> …` en una tarea suelta con la definición `campus-locator-dev-worker` (o
con `DELETE /v1/admin/videos/{id}` cuando BE-4.1 esté «Hecho»). Al empezar borra los restos de ejecuciones
interrumpidas (preparación, §1). C6b no crea nada: solo intenta borrar un video ajeno y comprueba que la orden se
niega (y la segunda con `--simular`). Si la tarea de la limpieza final sale con 0 pero su log no trae la línea
`LIMPIEZA`, no es un fallo (el log puede llegar incompleto).

Cada `PUT` correcto genera un evento de S3 en la cola `ingesta` (6 por ejecución: 3 de C1b, 1 de C2c, 1 de C3b y 1
del video `-b`; el `PUT` rechazado de C3a no genera ninguno). El script no los borra (ARCHITECTURE §5.11, R13): antes de BE-2.2 esperan hasta la
retención de la cola (4 días); con BE-2.2, el `worker` los descarta porque las imágenes ya no existen. Si el `worker` está encendido,
puede procesar las fotos antes de que se borren (C2b y C5 lo admiten). Ejecuta 3 tareas sueltas de `worker` (C6a, C6b y la
limpieza; una más si hay restos al empezar y otra si hay videos ajenos en C6b).

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate21.py --entorno dev
```

**Variables.**

| Variable | `dev` |
|---|---|
| `AWS_PROFILE` | Obligatoria, también si es el perfil por defecto (`export AWS_PROFILE=default`). Necesita leer el secreto `admin-inicial`, `head-bucket`, `head-object` y `list-objects-v2` en el bucket del dataset (P4 lo comprueba), `ecs run-task`/`describe-*` en `campus-locator-dev`, `iam:PassRole` de los roles de `worker` y `logs:GetLogEvents` en `/campus-locator/dev/worker` (con `campus-admin`, sí) |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) |

Herramientas: `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`. Duración
aproximada: 20–25 min (C3a espera ~15 min; cada tarea suelta, 1–2 min). El informe queda en
`project/.validacion/BE-2.1-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe RUTA`. No necesita `embedding`: no lo
enciende ni lo toca.

**Preparación en `dev`.**

1. Pruebas y estilo en la máquina, con PostgreSQL para las pruebas `base` (el `db` del compose sirve):
   ```bash
   cd BACKEND_FASTAPI/project
   docker compose up -d --wait db
   uv sync --locked --group ops
   uv run ruff check . && uv run ruff format --check .
   PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator \
     PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
   ```
   Esperado: `All checks passed!`, `… files already formatted` y todas las pruebas pasan. Hasta BE-2.2 se omitía la
   de Pillow (`test_jpeg_sintetico_se_decodifica_con_pillow`); desde BE-2.2 (ARCHITECTURE 0.9.0) Pillow está en las
   dependencias y también corre.
2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
   `migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker` (ARCHITECTURE §4.2). Esperado:
   el workflow en verde.
3. Comprobar que `api` sirve ese commit y que la recolección existe (sin token, `401`; con la imagen de BE-1.3,
   `404`):
   ```bash
   URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
   curl -s $URL/health
   curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/collect/videos -H 'Content-Type: application/json' -d '{}'
   ```
   Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `401`.
4. Comprobar que la revisión de `worker` lleva la misma imagen que `api` (si no, P5 termina con 2: «imágenes
   distintas»):
   ```bash
   export AWS_PROFILE=campus-admin
   aws ecs describe-task-definition --task-definition campus-locator-dev-worker --query 'taskDefinition.containerDefinitions[0].image' --output text
   aws ecs describe-task-definition --task-definition $(aws ecs describe-services --cluster campus-locator-dev --services api --query 'services[0].taskDefinition' --output text) --query 'taskDefinition.containerDefinitions[0].image' --output text
   ```
   Esperado: dos líneas iguales, `…/campus-locator/backend:<SHA del commit>`.
5. (Opcional) Si la máquina estuvo suspendida, el reloj de WSL puede ir atrasado; reiniciar WSL (`wsl --shutdown`
   desde Windows) suele sincronizarlo (sin comprobar). No es imprescindible: el validador corrige el desfase con la
   hora de S3 y P4 lo informa.

**Ejecución.**

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate21.py --entorno dev
```

Esperado (unos 20–25 min; el progreso de la espera de C3a sale por stderr): código 0, con `[PASA]` en P1–P5 y en C1a,
C1b, C1c, C2a, C2b, C2c, C3a, C3b, C4, C5, C6a y C6b; P4 termina en `reloj local +N s respecto a S3`; antes de C1,
`[PREPARACION] sin restos validacion- de ejecuciones anteriores` (o `restos borrados: {"videos": n, …}`); C3a con
`(desfase local +N s)`; C4 con `pendiente_subida=0 subida=4 procesada=0 error=0 · estado procesando (el de §5.5)` si
el `worker` está apagado; C6b con `… con --simular → 1 y sigue existiendo (200)` si hay videos reales; y al final
`[LIMPIEZA] videos de prueba borrados: {"videos": 1, "objetos": 4}`. Con eso, la fila BE-2.1 de PLAN §3 pasa a
«Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

En `local` no se ejecuta (S3 no se emula): el script termina con 3 (`BE-2.1 solo admite el entorno: dev`). Lo que sí se
comprueba en `local` está en las pruebas del paso 1 (S3 simulado y el validador contra un mundo falso,
`tests/ops/test_validate21.py`).
