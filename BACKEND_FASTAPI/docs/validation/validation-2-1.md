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

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | URL de la API | `VALIDACION_API_URL`, o el output `api_base_url` (`terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -json`) + `/v1`; `GET /v1/health` → `200` |
| P3 | `BE-1.3` en «Hecho»: login de admin | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` |
| P4 | Bucket del dataset accesible | Output `bucket_dataset`; `s3api head-bucket --bucket campus-locator-dev-dataset-648617469176` sin error |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `POST /v1/collect/videos` con el cuerpo de §5.4, `ref_cliente` y `nombre` = `validacion-21-<AAAAMMDD-HHMMSS>`, `total_fotos: 4` y coordenadas fuera del campus | `201` con un `VideoResumen` en `estado = "pendiente"` |
| C1b | `POST /v1/collect/videos/{id}/images` con 4 elementos (`orden` 1–4, `rumbo` 0/90/180/270, `bytes` = tamaño real) y `PUT` de las fotos 1–3 a `subida.url` enviando exactamente `subida.encabezados` | Las 4 en `pendiente_subida` con `subida.metodo = "PUT"`; los tres `PUT` dan `200` |
| C1c | `s3api head-object --bucket campus-locator-dev-dataset-648617469176 --key dataset/{video_id}/{imagen_id}.jpg` de las fotos 1–3 | Existen, con `ContentType = image/jpeg` y `ContentLength` igual a los bytes enviados |
| C2a | Repite `POST /v1/collect/videos` con el mismo cuerpo | `200` con el mismo `id` y el mismo `numero` |
| C2b | Repite `POST …/images` con los 4 elementos | Mismo `id` para cada `orden`; fotos 1–3 con `subida = null`; foto 4 con `subida` no nula |
| C2c | Repite el `PUT` de la foto 1 (misma URL y cuerpo); `s3api list-objects-v2 --prefix dataset/{video_id}/` | El `PUT` da `200` y hay exactamente 3 objetos |
| C3a | Con la URL de la foto 4 obtenida en C1b, espera a que pase su `expira_en` (`PRESIGN_PUT_TTL_S` = 900 s) más 10 s y hace el `PUT` | `403` de S3 con `<Code>AccessDenied</Code>` y el mensaje `Request has expired` |
| C3b | `POST …/images` solo con el elemento `orden: 4`; `PUT` con la URL nueva; `head-object` de su clave | `expira_en` en el futuro, `PUT` `200` y el objeto existe |
| C4 | Justo después de los `PUT` (sin esperar al `worker`), `POST /v1/collect/videos/{id}/complete` dos veces | `200`; `conteo` con exactamente `pendiente_subida`, `subida`, `procesada` y `error`, que suman 4, con `pendiente_subida = 0` (el `HEAD` de `complete` marca `subida` lo que ya está en S3, §4.5); la segunda respuesta tiene el mismo `id` y la misma suma |
| C5 | `GET /v1/admin/videos/{id}` y `GET /v1/admin/videos?q=<nombre del video>` | El detalle es un `VideoResumen` con `fotos` en orden 1–4 y el mismo `conteo` que la última respuesta de C4; el listado lo incluye |
| C6a | Crea un segundo video `validacion-21-<ts>-b` con 1 foto subida y lanza `limpiar-validacion --video <id>` con la definición `campus-locator-dev-worker`; luego `GET /v1/admin/videos/{id}` y `s3api list-objects-v2 --prefix dataset/{id}/` | La tarea sale con 0 y su log tiene `LIMPIEZA {"videos": 1, …}`; el `GET` da `404 NO_ENCONTRADO` y no quedan objetos |
| C6b | Lanza `limpiar-validacion --video <uuid inexistente>` y, si `GET /v1/admin/videos` muestra algún video cuyo nombre no empieza por `validacion-` (por ejemplo, del dataset real), otra vez con su `id` | Las dos tareas salen con 1 y ese video sigue existiendo (`GET /v1/admin/videos/{id}` → `200`). Sin videos así, solo se comprueba la primera |

Orden de ejecución: C1, C2, C3, C4, C5, C6 (la espera de C3a es casi toda la duración). El script nunca imprime las URLs
prefirmadas: solo informa el código de estado de cada `PUT`.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea un video `validacion-21-<AAAAMMDD-HHMMSS>` (mismo valor en `ref_cliente` y `nombre`, único por ejecución) con 4
JPEG sintéticos de 1024×768 generados por el script (semilla distinta en cada ejecución) y coordenadas fuera del campus,
y el video `-b` de C6a. Los eventos de S3 llegan a `ingesta`; si el `worker` está encendido, los procesa. Como
`ref_cliente` es único por ejecución, los restos no interfieren con la idempotencia que mide C2.

Limpieza (backend `ARCHITECTURE.md` §5.11): al terminar, también si algo falló, borra su video con `limpiar-validacion
--video <id>` en una tarea suelta con la definición `campus-locator-dev-worker` (o con `DELETE /v1/admin/videos/{id}` si
BE-4.1 está «Hecho»). Al empezar, si `GET /v1/admin/videos?q=validacion-` devuelve restos de una ejecución interrumpida,
los borra igual (`limpiar-validacion` sin `--video`). C6b no crea nada: solo intenta borrar
un video ajeno y comprueba que la orden se niega.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate21.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`
(opcionales; ver `ARCHITECTURE.md` §5.11). Duración aproximada: 20 minutos.
