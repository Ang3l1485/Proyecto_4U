# Validación 1-3 — BE-1.3 Autenticación

| Campo | Valor |
|---|---|
| Lote | `BE-1.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate13.py` |
| Entornos | `dev`, `local` (ningún criterio depende de S3 ni SQS) |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de `comun.py` que usa este script: `ClienteApi`, `EntornoBackend`,
`credenciales_admin`, `leer_secreto` y el usuario de prueba).

## 1. Precondiciones

Si alguna no se cumple porque otro lote no está listo, el script termina con código 2 y el lote queda `Bloqueado`; si
falla por credenciales, permisos, herramientas o variables, con código 3. Se detiene en la primera que no se cumple. En
`dev` evalúa P1 a P5; en `local`, P2, P3, P4 y P6.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-1.2` en «Hecho»: base migrada y `api` respondiendo | `GET /v1/health/ready` → `200` con `"db": "ok"` (si no responde o da otro código: 2). Guarda la hora del encabezado `Date` menos 5 s como inicio de C6. La URL es `VALIDACION_API_URL` o, en `dev`, el output `api_base_url` + `/v1`; en `local`, sin `VALIDACION_API_URL`: código 3 |
| P3 | Credenciales del admin | `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`; en `dev`, si falta alguna, `secretsmanager get-secret-value --secret-id campus-locator/dev/admin-inicial` (claves `correo`, `password`). Sin ninguna de las dos: código 3 |
| P4 | Clave de firma de los JWT (C1 y C4b) | `dev`: `secretsmanager get-secret-value --secret-id campus-locator/dev/jwt` (clave `secret`); `local`: `JWT_SECRET` con que se levantó el compose (sin ella: código 3) |
| P5 | Solo `dev`: tareas sueltas lanzables | `ecs describe-task-definition` de `campus-locator-dev-migrate` y `campus-locator-dev-validacion`; outputs `subredes_tareas` y `sg_migrate` |
| P6 | Solo `local`: entorno levantado | `docker compose ps --format json` en `project/` muestra `db` y `api` en marcha |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | `POST /v1/auth/login` con `{"identificador": "<correo admin>", "password": "<contraseña admin>"}`; decodifica el JWT y verifica la firma a mano (HMAC-SHA256 con los bytes UTF-8 de la clave de P4) | `200` con exactamente `token`, `expira_en` y `usuario` (`id`, `nombre`, `correo`, `rol`); `alg = HS256`; la firma corresponde; claims exactamente `iss`, `sub`, `rol`, `nombre`, `iat`, `exp`, `jti`; `iss = "campus-locator-api"`, `sub = usuario.id`, `rol = "admin"`, `nombre = usuario.nombre`, `jti` no vacío, `exp − iat = 43200` (`JWT_TTL_MIN`), `expira_en` = `exp` en ISO-8601 con `Z` y `usuario.correo` = el correo en minúsculas. Un `404` dice «¿está desplegado BE-1.3?» |
| C2 | Login con `{"identificador": "validacion-noexiste-<uuid>@campus.edu.co", "password": "validacion-pw-<uuid>"}` y otro con el correo del admin y la contraseña `validacion-pw-<uuid>` | Ambos `401` con `codigo = "CREDENCIALES_INVALIDAS"` y cuerpos idénticos (`mensaje` y `detalle` incluidos). El detalle informa lo que tardó cada uno (no se compara: en `dev` lo domina la red) |
| C5 | Crea o reactiva el usuario de prueba (§4) e inicia sesión con él; con ese token, `GET /v1/admin/stats/uso`; con el token de admin, la misma ruta | Login `200` con `usuario.rol = "user"`; la ruta da `403 SIN_PERMISOS` con el token `user` y `501 NO_IMPLEMENTADO` con el de admin |
| C3 | `python -m app.cli desactivar-usuario --correo validacion+user@campus.edu.co` (tarea suelta de `migrate`); luego login de ese usuario con su contraseña correcta y, con el token que obtuvo en C5, `GET /v1/admin/stats/uso` | El comando termina con 0; el login da `401` con un cuerpo idéntico al de C2; el token anterior da `401 TOKEN_INVALIDO` (§5.2) |
| C4a | Cambia un carácter **del medio** de la firma del token de C1 (el último puede no cambiar los bytes) y llama a `GET /v1/admin/stats/uso` | `401 TOKEN_INVALIDO` |
| C4b | Firma con la clave de P4 un token con los claims de C1 pero `iat` = hace 2 h y `exp` = hace 1 h; misma ruta | `401 TOKEN_EXPIRADO` |
| C6 | SQL: `SELECT count(*) FILTER (WHERE actor_id IS NULL), count(*) FILTER (WHERE actor_id IS NOT NULL), count(*) FILTER (WHERE detalle::text LIKE '%validacion-pw-%') FROM auditoria WHERE accion = 'usuario.login' AND creado_en >= '<inicio de P2>'` | Fallidos ≥ los `401` de login que recibió el script y correctos ≥ sus `200` (con todas las comprobaciones, 3 —C2 ×2 y C3— y 2 —C1 y C5—), y 0 filas con una contraseña de prueba. Puede contar más si otra ejecución terminó menos de 5 s antes |

Orden de ejecución: C1, C2, C5, C3, C4a, C4b, C6 (C3 desactiva al usuario que usa C5 y reutiliza su token). Los tokens
y el usuario de prueba se piden la primera vez que una comprobación los necesita, así `--solo C3` o `--solo C4` también
funcionan. Entre dos logins espera al menos 0,6 s; un `429` **de API Gateway** (cuerpo `{"message": …}`) se reintenta
tras 1, 2, 4 y 8 s (*throttling* de `POST /v1/auth/login`: 2 req/s y ráfaga 5, aproximado; infra §3.3 y §5.10), y un
`500 {"message": "Internal Server Error"}` de API Gateway (`api` sin instancias, infra §5.13) tras 2, 4 y 8 s. Los 429
y 500 del backend no se reintentan. La contraseña del admin nunca se pasa a una tarea suelta.

**Tarea migrate** = `ecs run-task` con la última revisión `ACTIVE` de `campus-locator-dev-migrate` (tiene que llevar la
misma imagen que el servicio `api`: si no, la comprobación falla con «¿terminó backend.yml en main?»), red
`subredes_tareas` + `sg_migrate` con IP pública, `startedBy = validate13` y `containerOverrides` con `command` (y
`environment` para la contraseña); su log se lee del stream `migrate/app/<id>` en `/campus-locator/dev/migrate`.
**SQL** = lo mismo con `campus-locator-dev-validacion` y `["psql", "-tAc", "<consulta>"]` (stream `validacion/app/<id>`
en `/campus-locator/dev/validacion`). En `local`: `docker compose run --rm -T [-e CREAR_USUARIO_PASSWORD] api python -m
app.cli …` y `docker compose exec -T db psql -U campus_app -d campus_locator -tAc "<consulta>"`. Las ayudas son las de
`comun.py` (ARCHITECTURE §5.11).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

La primera comprobación que necesita el usuario `validacion+user@campus.edu.co` (C5, o C3 con `--solo`) lo crea o lo
reactiva con `["python", "-m", "app.cli", "crear-usuario", "--correo", "validacion+user@campus.edu.co", "--nombre",
"validacion-usuario", "--rol", "user"]`, pasando una contraseña aleatoria `validacion-pw-<uuid>` en
`CREAR_USUARIO_PASSWORD` (variable del *override* de la tarea o del proceso de `docker compose`; nunca en el comando
ni impresa). Si una ejecución anterior lo dejó, `crear-usuario` lo actualiza y lo reactiva (§5.9): no hace falta tocar
la base. Va dentro de la comprobación para que un fallo cuente como `falla` (1) del lote.

Al terminar el usuario queda desactivado (C3; si C3 no llegó a correr, la limpieza lanza el mismo
`desactivar-usuario`). El script da por posible que quede activo **antes** de lanzar `crear-usuario`: si la tarea lo
reactiva y después falla la espera o la lectura del log, la limpieza lo desactiva igual; si no llegó a existir
(`usuario_no_encontrado`), la limpieza lo da por bueno. No hay borrado de usuarios, así que la fila permanece inactiva. Las filas de `auditoria` se
conservan (son registro). No crea videos, lugares ni alertas. La ruta reservada responde un `501` por ejecución, que
cuenta como 5xx para la alarma de la API (más de 5 en 5 min).

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate13.py --entorno dev
uv run --group ops python src/ops/validate13.py --entorno local   # con docker compose up en marcha
```

**Variables.**

| Variable | `dev` | `local` |
|---|---|---|
| `AWS_PROFILE` | Obligatoria, también si es el perfil por defecto (`export AWS_PROFILE=default`) | No se usa |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) | Obligatoria: `http://localhost:8000/v1` |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) | Obligatorias: `admin@campus.edu.co` / `local-solo-desarrollo-admin` (las del compose) |
| `JWT_SECRET` | No se usa (secreto `campus-locator/dev/jwt`) | Obligatoria: `local-solo-desarrollo-no-usar-en-aws` (la del compose) |

Herramientas: en `dev`, `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`; en
`local`, Docker con `docker compose`. Duración aproximada: 4–6 min en `dev` (tres tareas sueltas: `crear-usuario`,
`desactivar-usuario` y la de SQL), 15 s en `local`. El informe queda en `project/.validacion/BE-1.3-<AAAAMMDD-HHMMSS>.json`
(hora UTC) o en `--informe RUTA`.

**Preparación en `dev`.**

1. Pruebas y estilo en la máquina, con `uv.lock` al día (PyJWT entró en BE-1.3), y con PostgreSQL para las pruebas
   `base` (el `db` del compose sirve):
   ```bash
   cd BACKEND_FASTAPI/project
   docker compose up -d --wait db
   uv sync --locked --group ops
   uv run ruff check . && uv run ruff format --check .
   PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator \
     PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
   ```
   Esperado: `All checks passed!`, `… files already formatted` y todas las pruebas pasan, sin omitidas.
2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
   `migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker` (ARCHITECTURE §4.2). Esperado: el
   workflow en verde.
3. Comprobar que `api` sirve ese commit y que el login existe:
   ```bash
   URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
   curl -s $URL/health
   curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/auth/login -H 'Content-Type: application/json' \
     -d '{"identificador":"validacion-noexiste@campus.edu.co","password":"validacion-pw-x"}'
   ```
   Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}` y `401` (con la imagen de BE-1.2, `404`).

**Ejecución.**

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate13.py --entorno dev
```

Esperado: código 0, con `[PASA]` en P1–P5 y en C1, C2, C5, C3, C4a, C4b y C6, y
`[LIMPIEZA] nada que limpiar (validacion+user@campus.edu.co ya quedó desactivado)`. C2 informa lo que tardó cada login
(en `dev`, sin comprobar; anotar los dos tiempos en la nota de PLAN §3, R12). Con eso, la fila BE-1.3 de PLAN §3 pasa a
«Hecho» con el commit, la fecha y la versión de ARCHITECTURE.

**En `local`** (no cierra el lote; comprobado así antes de entregar):

```bash
cd BACKEND_FASTAPI/project
docker compose up -d --build --wait db api worker
docker compose run --rm -T api python -m app.cli migrar
export VALIDACION_API_URL=http://localhost:8000/v1 VALIDACION_ADMIN_CORREO=admin@campus.edu.co
export VALIDACION_ADMIN_PASSWORD=local-solo-desarrollo-admin JWT_SECRET=local-solo-desarrollo-no-usar-en-aws
uv run --group ops python src/ops/validate13.py --entorno local
```

Esperado: `[PASA]` en P2, P3, P4, P6 y en las siete comprobaciones; C6 dice
`3 fallidos (≥ 3), 2 correctos (≥ 2), 0 con contraseña` (más si se repite antes de 5 s) y el código es 0. Repetirlo da
lo mismo: el usuario de prueba se reactiva y vuelve a quedar desactivado.
