# Validación 2-4 — BE-2.4 Diagnóstico de búsqueda

| Campo | Valor |
|---|---|
| Lote | `BE-2.4` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate24.py` |
| Entornos | `dev` (necesita S3, SQS y el `worker` para indexar las fotos de prueba) |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P1 es de credenciales: código 3).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-2.2` en «Hecho» y dentro del horario: las fotos de prueba llegan a `procesada` | `PLAN.md` §3 marca BE-2.2 «Hecho»; `GET /v1/health/ready` → `"db": "ok"` y `"embedding": "ok"`; hora `America/Bogota` entre 06:00 y 21:30 |
| P3 | Login de admin | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` |
| P4 | Recursos para inspeccionar | Outputs `bucket_dataset`, `subredes_tareas` y `sg_migrate`; `ecs describe-task-definition` de `campus-locator-dev-validacion`, `campus-locator-dev-migrate` y `campus-locator-dev-worker` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Crea el video `validacion-24-<ts>` con 3 JPEG sintéticos de 1024×768 muy distintos entre sí (patrones y colores generados con semilla), con el flujo de BE-2.1, y espera en `GET /v1/admin/videos/{id}` a que las 3 estén `procesada` (máx. 10 min). Envía cada uno, con los mismos bytes, a `POST /v1/admin/diagnostico/vecinos?k=5` | `200` en las tres; `version_vector = dinov2-vitb14/pp-v1`; el primer vecino es la propia `imagen_id`, con `video_id` = el video de prueba y `similitud` ≥ 0,95 |
| C2a | Lee `GET /v1/admin/stats` → `total_fotos` (N). Envía con `k=5` una cuarta imagen sintética que no se subió (ruido aleatorio) | `vecinos` tiene `min(5, N)` elementos, con `similitud` de mayor a menor; no se descarta ninguno por `LOC_SIM_MIN` (si alguna similitud es < 0,55, se anota en el detalle como evidencia) |
| C2b | La misma cuarta imagen con `k=1` y con `k=50` | `1` y `min(50, N)` vecinos, ordenados; los `imagen_id` de `k=1` y de `k=5` empiezan igual |
| C3a | `k=0`, `k=51` y `k=abc` con una foto válida | `422 VALIDACION` en los tres, con `detalle.campos` que nombra `k` |
| C3b | Sin parte `foto`; una parte PNG; un JPEG de 1,6 MB (relleno sintético) | `400 FOTOS_INVALIDAS` en los tres, con `detalle.indice = 0` |
| C3c | Crea o reactiva `validacion+user@campus.edu.co` (§4), inicia sesión con él y llama al endpoint con una foto válida; repite sin encabezado `Authorization` | `403 SIN_PERMISOS` con el token `user` y `401 NO_AUTENTICADO` sin token |
| C4a | Antes de C1 anota la lista de claves de `s3api list-objects-v2 --bucket campus-locator-dev-dataset-648617469176` (paginado) y, con la tarea de validación, `SELECT count(*) FROM eventos_localizacion`; tras C3 las repite | Las únicas claves nuevas son `dataset/<video de prueba>/…` y `thumbs/<video de prueba>/…` (las tres fotos de C1); el conteo de `eventos_localizacion` no cambió |
| C4b | `logs filter-log-events` de `/campus-locator/dev/api` y `/campus-locator/dev/embedding` desde el inicio | Ningún evento contiene `/9j/` (comienzo de un JPEG en base64) ni pesa más de 16 KB |

Orden de ejecución: C4a (lecturas iniciales), C1, C2, C3, C4a (lecturas finales), C4b. Las consultas a la base usan
la tarea `campus-locator-dev-validacion` con `psql -tAc`, como en [`validation-1-2.md`](./validation-1-2.md) §2. C4a
supone que nadie sube fotos ni localiza en `dev` mientras corre; si el conteo no cuadra, el detalle muestra los dos
valores para descartar actividad ajena antes de repetir.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea el video `validacion-24-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 3 JPEG sintéticos en una coordenada
fuera del campus, y usa el usuario `validacion+user@campus.edu.co`, que crea o reactiva con `crear-usuario --rol user`
(contraseña aleatoria en `CREAR_USUARIO_PASSWORD`, nunca impresa) en una tarea suelta de `migrate`. Las fotos de C2 y
C3 no se suben a ningún sitio.

Al terminar, también si algo falló: borra el video con `limpiar-validacion --video <id>` en una tarea suelta con la
definición `campus-locator-dev-worker` (o con `DELETE /v1/admin/videos/{id}` si BE-4.1 está «Hecho») y desactiva el
usuario con `desactivar-usuario`. Al empezar, si `GET /v1/admin/videos?q=validacion-` devuelve restos de una ejecución
interrumpida, los borra igual (`limpiar-validacion` sin `--video`). Todo según `ARCHITECTURE.md` §5.11.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate24.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`
(opcionales; ver `ARCHITECTURE.md` §5.11). Duración aproximada: 15 minutos (ingesta de las tres fotos y cinco tareas
sueltas).
