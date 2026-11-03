# Validación 3-1 — BE-3.1 Lugares

| Campo | Valor |
|---|---|
| Lote | `BE-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate31.py` |
| Entornos | `dev` (cierra el lote) y `local` (contra `docker compose`): ningún criterio depende de S3, SQS ni `embedding` |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-1.3 y BE-3.1: `ClienteApi`, `credenciales_admin`, `lugares_validacion`,
`borrar_lugares_restos`…). Cómo funcionan los endpoints: `ARCHITECTURE.md` §4.9; sus contratos, §5.3 y §5.5.

Desde ARCHITECTURE 0.11.0 el lote es solo de lugares: las comprobaciones de alertas pasaron a
[`validation-3-3.md`](./validation-3-3.md) (BE-3.3).

## 1. Precondiciones

Si una no se cumple porque otro lote no está listo, el script termina con código 2 y el lote queda `Bloqueado`; si
falla por credenciales o variables, con código 3. Se detiene en la primera que no se cumple y no crea nada. En `dev`
evalúa P1, P2 y P3; en `local`, P2 y P3.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` (para el output `api_base_url` y el secreto del admin) | `aws sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | URL de la API y base (BE-1.2) | `VALIDACION_API_URL` o, en `dev`, el output `api_base_url` + `/v1` (en `local`, sin `VALIDACION_API_URL`: código 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: código 2) |
| P3 | Login de admin (BE-1.3) y BE-3.1 desplegado | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (en `dev`, si faltan, el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es código 3; un `404`, código 2); `GET /v1/places` → `200` (un `404` es código 2: «BE-3.1 sin desplegar») |

**Preparación** (tras las precondiciones; un fallo solo se avisa): borra todos los lugares cuyo nombre normalizado
empieza por `validacion-` (de cualquier lote) que haya dejado una ejecución interrumpida: `GET /v1/admin/places?q=
validacion-` y `DELETE /v1/admin/places/{id}` de cada uno (`comun.borrar_lugares_restos`). Imprime `[PREPARACION] …`.

## 2. Comprobaciones automáticas

`<P>` = `validacion-31-<AAAAMMDD-HHMMSS>` (hora UTC de la ejecución). Lugares de prueba (cuerpos de `LugarEntrada`):
A `<P> Biblioteca Lago` (`biblioteca`, en (0.001, 0.001), con 2 alias, `descripcion` y `referencias`), B `<P> Bloque
Sur` (`bloque`, en (0.001, 0.001)), C `<P> Entrada Este` (`entrada`, en (0.001, 0.002), 111,2 m al este de B) y D
`<P> Cafe Norte` (`cafeteria`, en (0.001, 0.001)).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `POST /v1/admin/places` de A; `GET /v1/places` sin token; `GET /v1/admin/places?q=<P en mayúsculas, con «VALIDACIÓN»> BIBLIOTECA` | `201` con exactamente los campos de `LugarAdmin` y los valores enviados, `imagen_url = null`, `total_fotos = 0`, `creado_en = actualizado_en`; A sale en `GET /v1/places` con exactamente los campos de `LugarPublico`, los mismos valores y `distancia_m = null`; la búsqueda (sin tildes ni mayúsculas) lo encuentra |
| C1b | `PUT /v1/admin/places/{A}` con nombre `<P> Bibliotéca Lago` (el mismo, con tilde), `categoria: "bloque"`, (0.0011, 0.0012), alias `["validacion bloque"]`, `referencias` nuevas y sin `descripcion` | `200` con esos valores (`descripcion = null`), `creado_en` sin cambios y `actualizado_en ≥ creado_en`; `GET /v1/places` y `GET /v1/admin/places` dan los valores nuevos |
| C1c | `DELETE /v1/admin/places/{A}`; las dos lecturas; `PUT` de A; otro `DELETE` de A | `204`; A ya no sale en ninguna de las dos; el `PUT` da `404 NO_ENCONTRADO`; el `DELETE` repetido, `204` |
| C2a | Crea B y C; `GET /v1/places?lat=0.001&lng=0.001` | Todos con `distancia_m` numérica, de menor a mayor; B es el primero, con `distancia_m` < 1; C sale con 111,2 ± 0,5 m |
| C2b | `GET /v1/places?lat=0.001&lng=0.001&categoria=entrada` | Todos de categoría `entrada`; C sí, B no |
| C2c | `GET /v1/places` sin posición | Todos con `distancia_m = null`, ordenados por nombre normalizado (la regla de §5.5, copiada en `comun.normalizar_nombre`) e `id`; B antes que C |
| C3a | Crea D; `POST` de `<P en mayúsculas> CAFE NORTE` | `201` y después `409 NOMBRE_DUPLICADO` |
| C3b | `POST` de `<P> Café Norte` y de `  <P>   Cafe  Norte ` (espacios de más); `GET /v1/admin/places?q=<P> cafe norte` | `409 NOMBRE_DUPLICADO` en los dos; la búsqueda devuelve solo D |
| C3c | `PUT /v1/admin/places/{B}` con el cuerpo de B y nombre `<P> CAFÉ NORTE` | `409 NOMBRE_DUPLICADO` y B conserva su nombre |
| C4a | `GET /v1/places?lat=0.001` (sin `lng`), `GET /v1/places?categoria=cocina`, `POST` con `nombre` de 1 carácter, con `lat: 91` y con 21 alias, y `PUT /v1/admin/places/no-es-uuid` | `422 VALIDACION` en los seis; en los cinco primeros, `detalle.campos` nombra `lng`, `categoria`, `nombre`, `lat` y `alias` |
| C4b | `GET` y `POST /v1/admin/places` sin `Authorization`; `GET /v1/places` con `Authorization: Bearer no-es-un-token` | `401 NO_AUTENTICADO` en los dos primeros (el `POST` no crea nada); `200` en el público |

Orden: C1a, C1b, C1c, C2a, C2b, C2c, C3a, C3b, C3c, C4a, C4b. Cada comprobación crea lo que le falta si se ejecuta sola
con `--solo` (p. ej. `--solo C3c` crea D y B). Un `POST` que responde `201` cuando se esperaba un rechazo apunta el
lugar para borrarlo al final. El script nunca imprime tokens ni contraseñas.

Lo que **no** comprueba (lo cubren las pruebas con base, `tests/base/test_lugares_base.py`): que las fotos de un lugar
borrado queden con `lugar = null` (asignar un lugar a una foto llega con BE-4.1, cuyo C5b lo usa), las filas de
`auditoria` (`lugar.crear`, `lugar.editar`, `lugar.eliminar`) y que un `PUT` sin cambios no escriba.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea hasta 4 lugares `validacion-31-<AAAAMMDD-HHMMSS> …` (A, B, C, D de §2) en (0.001, 0.001) y (0.001, 0.002), fuera
del campus, para que ninguna app de `dev` los proponga como destino cercano. No crea videos, alertas ni usuarios, y no
lanza tareas de ECS.

Limpieza (siempre, también si algo falló; no con `--sin-limpieza`): `DELETE /v1/admin/places/{id}` de cada lugar que
siga existiendo con el prefijo de esta ejecución y de los que apuntó; imprime `[LIMPIEZA] lugares de prueba borrados:
<n>` (los que aún existían: 3 en una ejecución completa, porque C1c ya borró A). Si el script se interrumpe, la
preparación de la siguiente ejecución borra los restos. Las filas de `auditoria` se conservan (son registro).

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` | `local` |
|---|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`), también si es el perfil por defecto. Necesita `sts:GetCallerIdentity` y leer el secreto `campus-locator/dev/admin-inicial` (si no se pasan `VALIDACION_ADMIN_*`); `terraform output` lee el estado de `envs/dev` | No se usa |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) | Obligatoria: `http://localhost:8000/v1` |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) | Obligatorias: `admin@campus.edu.co` / `local-solo-desarrollo-admin` (las del compose) |

Herramientas: en `dev`, `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`;
en `local`, Docker con `docker compose`. Duración: menos de 1 min en `dev` (unas 40 peticiones; sin tareas de ECS) y
unos 5 s en `local`. El informe queda en `project/.validacion/BE-3.1-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en
`--informe RUTA`. Recursos compartidos: no usa `embedding`, colas ni tareas; mientras corre, nadie más crea ni borra
lugares en `dev` (los validadores de BE-2.3 y BE-4.1 también crean lugares de prueba y la preparación de cada uno
borra los `validacion-` de los demás), ni hace push a `main` con cambios en `BACKEND_FASTAPI/project/**`.

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo en la máquina, con el PostgreSQL del compose para las pruebas `base` (incluyen el validador contra
el backend real, `tests/ops/test_validate31.py`):

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

3. Comprobar que `api` sirve ese commit y que las rutas existen (desde `BACKEND_FASTAPI/project`; con la imagen
anterior a BE-3.1, `404` y `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' $URL/places
curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/admin/places
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}`, `200` y `401`.

**Ejecución en `dev`.**

4. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate31.py --entorno dev
```

Esperado (menos de 1 min): código 0, con `[PASA]` en P1, P2, P3 y en C1a, C1b, C1c, C2a, C2b, C2c, C3a, C3b, C3c, C4a y
C4b. P2 termina en `… /v1/health/ready → "db": "ok"`; P3 es `login admin 200 (rol admin) · GET /v1/places → 200 (<n>
lugares)`; después `[PREPARACION] sin lugares validacion- de ejecuciones anteriores` (o `lugares validacion- borrados:
<n>`); C1a `POST → 201 LugarAdmin · en GET /v1/places (distancia_m null) · GET /v1/admin/places?q=VALIDACIÓN-31-… BIBLIOTECA
lo encuentra`; C1b `PUT → 200 con nombre con tilde (mismo nombre), categoría, posición, alias y textos nuevos, en las dos
lecturas`; C1c `DELETE → 204 · fuera de las dos lecturas · PUT → 404 NO_ENCONTRADO · DELETE repetido → 204`; C2a
`?lat=0.001&lng=0.001 → <n> lugares de menor a mayor distancia · B primero con 0.0 m · C a 111.2 m`; C2b
`?lat=0.001&lng=0.001&categoria=entrada → lugares: <n>, todos entrada (C sí, B no)`; C2c `sin posición → <n> lugares por
nombre normalizado, distancia_m null`; C3a `«validacion-31-… Cafe Norte» → 201 · «VALIDACION-31-… CAFE NORTE» → 409
NOMBRE_DUPLICADO`; C3b `«validacion-31-… Café Norte» y «validacion-31-…   Cafe  Norte» con espacios de más → 409
NOMBRE_DUPLICADO · sigue habiendo 1`; C3c `PUT de B con «validacion-31-… CAFÉ NORTE» → 409 NOMBRE_DUPLICADO y B sin
cambios`; C4a `6 entradas no válidas → 422 VALIDACION con el campo en detalle.campos`; C4b `sin token: GET y POST
/v1/admin/places → 401 NO_AUTENTICADO · GET /v1/places con token no válido → 200`; y al final `[LIMPIEZA] lugares de
prueba borrados: 3`. Con eso, el maestro pasa la fila BE-3.1 de PLAN §3 a «Hecho» con el commit, la fecha y la versión
de ARCHITECTURE.

**En `local`** (no cierra el lote; así se comprobó antes de entregar, 2026-10-25). Desde `BACKEND_FASTAPI/project`:

5. Levantar la base y la API con el código de la copia de trabajo y migrar (si `db` ya estaba en marcha, sigue igual):

```bash
docker compose up -d --build --wait db api
docker compose run --rm -T api python -m app.cli migrar
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/v1/places
```

Esperado: `Container campus-locator-backend-api-1 Healthy`, el evento `migracion_terminada` (con la base ya migrada,
`"aplicada": false` y `"admin_inicial": "ya_habia_admin"`) y `200`.

6. Lanzar el validador:

```bash
export VALIDACION_API_URL=http://localhost:8000/v1 VALIDACION_ADMIN_CORREO=admin@campus.edu.co
export VALIDACION_ADMIN_PASSWORD=local-solo-desarrollo-admin
uv run --group ops python src/ops/validate31.py --entorno local
```

Esperado (unos 5 s): `[PASA]` en P2, P3 y en las once comprobaciones, con los mismos detalles que en `dev` (P2 con
`http://localhost:8000/v1`), `[LIMPIEZA] lugares de prueba borrados: 3` y `== Resultado: pasa (código 0)`. Repetirlo da
lo mismo.

7. Apagar lo que se levantó en el paso 5 (si `db` ya estaba en marcha antes, dejarla):

```bash
docker compose rm -sf api
docker compose ps --format '{{.Service}} {{.State}}'
```

Esperado: `api` ya no aparece (y `db running` si estaba antes; si no, `docker compose stop db`).
