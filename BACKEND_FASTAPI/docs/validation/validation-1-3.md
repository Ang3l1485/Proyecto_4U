# Validación 1-3 — BE-1.3 Autenticación

| Campo | Valor |
|---|---|
| Lote | `BE-1.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate13.py` |
| Entornos | `dev`, `local` (ningún criterio depende de S3 ni SQS) |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-1.2` en «Hecho»: base migrada con el esquema de §5.7 | `GET /v1/health/ready` → `200` con `"db": "ok"` |
| P3 | Credenciales del admin | `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`; en `dev`, si faltan, `secretsmanager get-secret-value --secret-id campus-locator/dev/admin-inicial` (claves `correo`, `password`). Sin ninguna de las dos: código 3 |
| P4 | Clave de firma de los JWT (C1 y C4b) | `dev`: `secretsmanager get-secret-value --secret-id campus-locator/dev/jwt` (clave `secret`); `local`: `JWT_SECRET` con que se levantó el compose |
| P5 | Solo `dev`: tareas sueltas lanzables | `ecs describe-task-definition` de `campus-locator-dev-migrate` y `campus-locator-dev-validacion`; outputs `subredes_tareas` y `sg_migrate` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | `POST /v1/auth/login` con `{"identificador": "<correo admin>", "password": "<contraseña admin>"}`; decodifica el JWT y verifica la firma con la clave de P4 | `200`; `alg = HS256`, `iss = "campus-locator-api"`, `sub = usuario.id`, `rol = "admin"`, `nombre = usuario.nombre`, `jti` presente, `exp − iat = 43200` (`JWT_TTL_MIN`) y `expira_en` igual a `exp` |
| C2 | Login con `{"identificador": "validacion-noexiste-<uuid>@campus.edu.co", …}` y otro con el correo del admin y la contraseña `validacion-pw-<uuid>` | Ambos `401` con `codigo = "CREDENCIALES_INVALIDAS"` y cuerpos idénticos (`mensaje` y `detalle` incluidos) |
| C3 | Tarea suelta de `migrate` con `["python", "-m", "app.cli", "desactivar-usuario", "--correo", "validacion+user@campus.edu.co"]`; luego login de ese usuario con su contraseña correcta, y con el token que obtuvo en C5, `GET /v1/admin/stats/uso` | La tarea sale con 0; el login da `401` con un cuerpo idéntico al de C2; el token anterior da `401 TOKEN_INVALIDO` (§5.2) |
| C4a | Cambia un carácter de la firma del token de C1 y llama a `GET /v1/admin/stats/uso` | `401 TOKEN_INVALIDO` |
| C4b | Firma con la clave de P4 un token con los *claims* de C1 pero `iat` = hace 2 h y `exp` = hace 1 h; misma ruta | `401 TOKEN_EXPIRADO` |
| C5 | Login de `validacion+user@campus.edu.co`; con ese token, `GET /v1/admin/stats/uso`; con el token de admin, la misma ruta | Login `200` con `usuario.rol = "user"`; la ruta da `403 SIN_PERMISOS` con el token `user` y `501 NO_IMPLEMENTADO` con el de admin |
| C6 | SQL: `SELECT count(*) FILTER (WHERE actor_id IS NULL), count(*) FILTER (WHERE actor_id IS NOT NULL), count(*) FILTER (WHERE detalle::text LIKE '%validacion-pw-%') FROM auditoria WHERE accion = 'usuario.login' AND creado_en >= '<inicio>'` | ≥ 3 intentos fallidos (C2 ×2 y C3), ≥ 2 con éxito (C1 y C5) y 0 filas con una contraseña de prueba |

Orden de ejecución: C1, C2, C5, C3, C4, C6 (C3 desactiva al usuario que usa C5 y reutiliza su token). Entre dos logins
espera ≥ 600 ms
(*throttling* de `POST /v1/auth/login`: 2 req/s, infra §5.10). La contraseña del admin nunca se pasa a una tarea suelta.
Tarea migrate y SQL: como en [`validation-1-2.md`](./validation-1-2.md) §2; en `local`, `docker compose run --rm api …`
y `psql` contra la base del compose.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Antes de C1 crea o reactiva el usuario `validacion+user@campus.edu.co` (rol `user`) con la tarea migrate y el comando
`["python", "-m", "app.cli", "crear-usuario", "--correo", "validacion+user@campus.edu.co", "--nombre",
"validacion-usuario", "--rol", "user"]`, pasando una contraseña aleatoria `validacion-pw-<uuid>` en
`CREAR_USUARIO_PASSWORD` (override de entorno de la tarea, nunca impresa). Si una ejecución anterior lo dejó,
`crear-usuario` lo actualiza y lo reactiva (§5.9): no hace falta tocar la base.

Al terminar el usuario queda desactivado (C3; si C3 no llegó a correr, la limpieza lanza el mismo
`desactivar-usuario`). No hay borrado de usuarios, así que la fila permanece inactiva. Las filas de `auditoria` se
conservan (son registro). No crea videos, lugares ni alertas.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate13.py --entorno dev
uv run --group ops python src/ops/validate13.py --entorno local   # con docker compose up en marcha
```

Variables: `AWS_PROFILE` (obligatoria en `dev`), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y
`VALIDACION_ADMIN_PASSWORD` (opcionales en `dev`, obligatorias en `local`); ver `ARCHITECTURE.md` §5.11. En `local`,
además, `JWT_SECRET`. Duración aproximada: 7 minutos en `dev` (cuatro tareas sueltas), 1 minuto en `local`.
