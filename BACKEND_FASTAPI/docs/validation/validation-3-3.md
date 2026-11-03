# Validación 3-3 — BE-3.3 Alertas

| Campo | Valor |
|---|---|
| Lote | `BE-3.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 (fuera del núcleo) |
| Script | `project/src/ops/validate33.py` |
| Entornos | `dev` (cierra el lote) y `local` (contra `docker compose`): ningún criterio depende de S3, SQS ni `embedding` |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11 (ayudas de BE-1.3, BE-2.3 y BE-3.3: `ClienteApi`, `credenciales_admin`, `resumen_panel`,
`alertas_validacion`, `borrar_alertas_restos`…, y la descripción de `validate33.py`). Cómo funcionan los endpoints:
`ARCHITECTURE.md` §4.11; sus contratos, §5.3 (`GET /v1/alerts`) y §5.5 (`/v1/admin/alerts`); decisiones, ADR-BE-10 y
ADR-BE-19.

Estas comprobaciones estaban en `validation-3-1.md` (C1, C2, C4 y C5 de entonces) y en `validation-2-3.md` (C1c)
hasta ARCHITECTURE 0.11.0, cuando las alertas salieron del núcleo (decisión del usuario, 2026-10-25).

## 1. Precondiciones

Si una no se cumple porque otro lote no está listo, el script termina con código 2 y el lote queda `Bloqueado`; si
falla por credenciales o variables, con código 3. Se detiene en la primera que no se cumple y no crea nada. En `dev`
evalúa P1, P2, P3 y P4; en `local`, P2, P3 y P4. P4 solo se evalúa si C5 está incluida (con `--solo C1,C2,C3,C4` no
hace falta el resumen del panel).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` (para el output `api_base_url` y el secreto del admin) | `aws sts get-caller-identity` → `Account`. Si falla: código 3 |
| P2 | URL de la API y base (BE-1.2) | `VALIDACION_API_URL` o, en `dev`, el output `api_base_url` + `/v1` (en `local`, sin `VALIDACION_API_URL`: código 3); `GET /v1/health/ready` → `200` con `"db": "ok"` (si no: código 2) |
| P3 | Login de admin (BE-1.3) y BE-3.3 desplegado | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (en `dev`, si faltan, el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` (un `401` es código 3); `GET /v1/alerts` sin token → `200` (un `404` es código 2: «BE-3.3 sin desplegar»); `GET /v1/admin/alerts` → `200` |
| P4 | Solo con C5: `BE-2.3` en «Hecho» y desplegado | En `dev`, la fila `BE-2.3` de `BACKEND_FASTAPI/docs/PLAN.md` §3 (de la copia desde la que se ejecuta) dice `Hecho` (`comun.lote_hecho`; si no: código 2). En los dos entornos, `GET /v1/admin/stats` → `200` (un `404` es código 2: «BE-2.3 sin desplegar») |

**Preparación** (tras las precondiciones; un fallo solo se avisa): borra todas las alertas vivas cuyo mensaje
normalizado empieza por `validacion-` (de cualquier lote) que haya dejado una ejecución interrumpida: `GET
/v1/admin/alerts?q=validacion-` y `DELETE /v1/admin/alerts/{id}` de cada una (`comun.borrar_alertas_restos`). Imprime
`[PREPARACION] …`.

## 2. Comprobaciones automáticas

`<P>` = `validacion-33-<AAAAMMDD-HHMMSS>` (hora UTC de la ejecución). Todas las alertas de prueba están en (0.001,
0.001), llevan el mensaje `<P> <texto>` y un id (UUID v4) que genera el validador, como la app, y que apunta **antes**
de enviarlo. La «caché» es la de la app (§5.3; `validate33.aplicar`): una respuesta con `completo = true` la reemplaza;
si no, se reemplaza por `id`, se quitan las que llegan con `activa = false` y las de `eliminadas`; no se filtra por
vigencia. Cada lectura de `GET /v1/alerts` exige `200`, exactamente los campos `generado_en`, `completo`, `alertas` y
`eliminadas`, `generado_en` con el formato `AAAA-MM-DDTHH:MM:SSZ` y exactamente los campos de `Alerta` en cada alerta;
se pide sin token (es público).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Toma `GET /v1/alerts` sin `desde` como caché inicial y guarda `generado_en`; crea con `PUT /v1/admin/alerts/{A}` la alerta A `{"lat": 0.001, "lng": 0.001, "mensaje": "<P> creada", "tipo": "obra", "radio_m": 15}`; pide `GET /v1/alerts?desde=<generado_en>` y la aplica | Caché inicial con `completo = true`, `eliminadas` vacía y todas `activa`; `PUT` → `201` con exactamente los campos de `AlertaAdmin`, los valores enviados (y los de por defecto: `prioridad` `normal`, `activa` `true`, vigencias `null`), el `id` de la ruta, `version = 1`, `creado_en = actualizado_en` y `creado_por = actualizado_por` (`{id, nombre}`); la diferencia trae `completo = false` y A con `version = 1` |
| C1b | `PUT` de A con mensaje `<P> editada`, `radio_m: 20` e `If-Match: 1`; otro `PUT` de A con `If-Match: 1` y otro mensaje; aplica la diferencia siguiente | El primero `200` con esos valores y `version = 2`; el segundo `409 CONFLICTO_VERSION`; la diferencia trae A en la versión 2 con el mensaje `editada` (el `409` no escribió) |
| C1c | `DELETE /v1/admin/alerts/{A}`; aplica la diferencia siguiente; repite el `DELETE`; `GET /v1/admin/alerts?q=<P>` | `204`; la diferencia trae el id de A en `eliminadas` y no en `alertas`; el `DELETE` repetido, `204`; A no está en el panel |
| C1d | `GET /v1/alerts` sin `desde` final | `completo = true`, `eliminadas` vacía y el mapa `id → version` de la caché (inicial + las tres diferencias) igual al de esa foto completa; A no está |
| C2 | Lee `GET /v1/alerts` (su `generado_en`); `DELETE /v1/admin/alerts/{uuid4 nuevo}`; pide la diferencia desde ese `generado_en` | `204`, y el id desconocido **no** sale en `eliminadas` (no dejó *tombstone*) |
| C3 | `PUT` de la alerta F `<P> futura` con `activa: true`, `vigencia_desde` = ahora + 2 días y `vigencia_hasta` = ahora + 3 días (sin fracciones, con `Z`); `GET /v1/alerts` sin `desde` | `201` con las dos fechas; F está en `alertas` de la foto completa con sus dos fechas iguales a las enviadas |
| C4 | Crea con `PUT` la alerta D; `POST /v1/admin/alerts/sincronizar` con `{"cambios": [{"op": "upsert", "alerta": {A2 válida}}, {"op": "upsert", "alerta": {B con "radio_m": 500}}, {"op": "eliminar", "id": "<D>"}]}`; `GET /v1/admin/alerts?q=<P>` | `200` con exactamente `generado_en` (formato de §5.1) y `resultados`; `resultados` en el mismo orden: A2 `ok` (`codigo` `null`), B `error` con `codigo = "VALIDACION"`, D `ok`; en el panel está A2 y no están B ni D |
| C5 | Lee `GET /v1/admin/stats` (s0, `comun.resumen_panel`); crea con `PUT` la alerta G (`activa: true`, sin vigencia) y la H (`activa: false`); lee otra vez (s1) | `201` en las dos y `s1.alertas_activas − s0.alertas_activas = 1` |

Orden: C1a, C1b, C1c, C1d, C2, C3, C4, C5. C1 va por pasos: con `--solo C1c` (o `C1d`) se hacen antes los pasos de C1
que falten; un paso que ya falló no se repite y la comprobación que depende de él falla con «depende de C1b, que
falló». Las demás comprobaciones crean lo que necesitan. Si C1d o C5 no cuadran, el detalle muestra los valores leídos
para descartar actividad ajena antes de repetir (el script supone que nadie más crea, cambia o borra alertas en `dev`
mientras corre). El script nunca imprime tokens ni contraseñas.

No hace falta esperar entre un cambio y la diferencia que lo recoge: la diferencia empieza 60 s antes de `desde`
(`MARGEN_DESDE_S`, §5.3), así que puede traer también cambios ya aplicados (aplicarlos otra vez no cambia la caché; por
eso C1d compara `id → version`, no el número de elementos).

Lo que **no** comprueba (lo cubren las pruebas con base, `tests/base/test_alertas_base.py`): las filas de `auditoria`
(`alerta.upsert`, `alerta.eliminar`) y los eventos; que un `PUT` sin cambios no escriba; restaurar una borrada con
`PUT` (`201`); el margen de 60 s exacto y la foto completa con un `desde` de hace más de 90 días o futuro; el orden y los
filtros del panel; los `422` (cuerpo, `If-Match`, sobre de `sincronizar`); dos `PUT` a la vez del mismo id nuevo; la
purga diaria de *tombstones* (`purgar_tombstones`; en `dev` no se puede esperar 90 días).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea hasta 7 alertas `validacion-33-<AAAAMMDD-HHMMSS> …` en (0.001, 0.001), fuera del campus, para que ninguna app de
`dev` las anuncie: A (C1; la borra la propia C1c), D (C4; la borra el `eliminar` de C4), A2 (C4), F (C3), G y H (C5);
B (C4) nunca se crea (su `upsert` no es válido). No crea videos, lugares ni usuarios, y no lanza tareas de ECS.

Limpieza (siempre, también si algo falló; no con `--sin-limpieza`): `DELETE /v1/admin/alerts/{id}` de cada alerta viva
con el prefijo de esta ejecución y de los ids que apuntó (`comun.borrar_alertas`; el `DELETE` de un id que no existe o
ya borrado también da `204`); imprime `[LIMPIEZA] alertas de prueba borradas: <n>` (las que aún estaban vivas: 4 en una
ejecución completa, A2, F, G y H). Si el script se interrumpe, la preparación de la siguiente ejecución borra los
restos. Cada alerta borrada deja su *tombstone* `ALERTAS_TOMBSTONE_DIAS` (90 días: sale como `eliminadas`, sin
contenido, en las diferencias de cualquier app; no se puede quitar antes) y las filas de `auditoria` se conservan (son
registro).

## 5. Cómo ejecutarlo

**Variables.**

| Variable | `dev` | `local` |
|---|---|---|
| `AWS_PROFILE` | Obligatoria (`campus-admin`), también si es el perfil por defecto. Necesita `sts:GetCallerIdentity` y leer el secreto `campus-locator/dev/admin-inicial` (si no se pasan `VALIDACION_ADMIN_*`); `terraform output` lee el estado de `envs/dev` | No se usa |
| `VALIDACION_API_URL` | Opcional (por defecto, output `api_base_url` + `/v1`) | Obligatoria: `http://localhost:8000/v1` |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Opcionales (por defecto, el secreto `admin-inicial`) | Obligatorias: `admin@campus.edu.co` / `local-solo-desarrollo-admin` (las del compose) |

Herramientas: en `dev`, `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, y `uv`;
en `local`, Docker con `docker compose`. Duración: menos de 1 min en `dev` (unas 40 peticiones; sin `embedding`, colas
ni tareas de ECS) y unos segundos en `local`. El informe queda en `project/.validacion/BE-3.3-<AAAAMMDD-HHMMSS>.json`
(hora UTC) o en `--informe RUTA`. Recursos compartidos: mientras corre, nadie más crea, cambia ni borra alertas en `dev`
(una app con el editor de alertas abierto y sincronizando, por ejemplo), ni hace push a `main` con cambios en
`BACKEND_FASTAPI/project/**`. Las precondiciones leen el PLAN de la copia local: para C5 en `dev`, la copia debe tener
BE-2.3 en «Hecho» (desde `cf4fcbb`).

**Preparación en `dev`** (en WSL, desde la raíz del monorepo).

1. Pruebas y estilo, con un PostgreSQL para las pruebas `base` (incluyen `tests/base/test_alertas_base.py` y el
validador contra el backend real de `tests/ops/test_validate33.py`):

```bash
cd BACKEND_FASTAPI/project
docker compose up -d --wait db
uv sync --locked --group ops
uv run ruff check . && uv run ruff format --check .
PRUEBAS_DB_URL=postgresql://campus_app:local-solo-desarrollo@localhost:5432/campus_locator PRUEBAS_DB_OBLIGATORIA=1 uv run --group ops pytest -q
```

Esperado: `All checks passed!`, `… files already formatted` y `… passed` sin fallos ni omitidas. Si Docker no arranca
en la máquina (como al construir BE-3.3), las pruebas con base se corren en el CI: un PR con la rama dispara
`backend.yml`, que en un PR ejecuta `ruff` y `pytest` con un PostgreSQL 17 + pgvector efímero y
`PRUEBAS_DB_OBLIGATORIA=1` **sin desplegar** (`validation-2-3.md` §5, paso 1). Así se comprobó BE-3.3: PR 10, run
40383029250 sobre `89f6a52`, 1003 pasan, ninguna omitida. Sin base, en la máquina donde se construyó: 741 pasan y 262
se omiten (las `base`).

2. Llevar el commit a `main`. `backend.yml` pasa las pruebas, publica `…/campus-locator/backend:<SHA>`, ejecuta
`migrate` (sin migraciones nuevas: `aplicada = false`) y actualiza `api` y `worker`. Esperado: el workflow en verde.

3. Comprobar que `api` sirve ese commit y que las rutas existen (desde `BACKEND_FASTAPI/project`; con la imagen
anterior a BE-3.3, `404` y `404`):

```bash
URL=$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1
curl -s $URL/health
curl -s -o /dev/null -w '%{http_code}\n' $URL/alerts
curl -s -o /dev/null -w '%{http_code}\n' $URL/admin/alerts
```

Esperado: `{"estado":"ok","version":"0.1.0","commit":"<SHA corto>"}`, `200` y `401` (la ruta de admin existe y pide
token).

**Ejecución en `dev`.**

4. Lanzar el validador (desde `BACKEND_FASTAPI/project`):

```bash
export AWS_PROFILE=campus-admin
uv run --group ops python src/ops/validate33.py --entorno dev
```

Esperado (menos de 1 min): código 0, con `[PASA]` en P1, P2, P3, P4 y en C1a, C1b, C1c, C1d, C2, C3, C4 y C5. P1 es
`cuenta 648617469176 (<usuario>)`; P2 termina en `… /v1/health/ready → "db": "ok"`; P3 es `login admin 200 (rol
admin) · GET /v1/alerts → 200 (<n> activas) · GET /v1/admin/alerts → 200`; P4, `BE-2.3 «Hecho» · GET /v1/admin/stats
→ 200`; después `[PREPARACION] sin alertas validacion- de ejecuciones anteriores` (o `alertas validacion- borradas:
<n>`); C1a `foto completa con <n> activas · PUT → 201 version 1 · GET ?desde=<generado_en> → completo false con la
alerta`; C1b `PUT If-Match: 1 → 200 version 2 · otro PUT If-Match: 1 → 409 CONFLICTO_VERSION · la diferencia trae la
v2`; C1c `DELETE → 204 · la diferencia trae el id en eliminadas · DELETE repetido → 204 · fuera del panel`; C1d `caché
por diferencias = foto completa (<n> alertas, mismo id → version)`; C2 `DELETE de un UUID que no existe → 204, sin
tombstone`; C3 `vigencia AAAA-MM-DDTHH:MM:SSZ – AAAA-MM-DDTHH:MM:SSZ → en la foto completa con sus dos fechas`; C4
`upsert válido → ok · upsert con radio_m 500 → error VALIDACION · eliminar → ok · panel: A sí, B y D no`; C5
`alertas_activas <a> → <a+1> (+1) con una activa y una inactiva nuevas`; y al final `[LIMPIEZA] alertas de prueba
borradas: 4` y `== Resultado: pasa (código 0)`. Con eso, el maestro pasa la fila BE-3.3 de PLAN §3 a «Hecho» con el
commit, la fecha y la versión de ARCHITECTURE. Así quedó la primera ejecución (2026-10-26, sobre `4885ad6`, informe
`BE-3.3-20261026-191602.json`, 27 s): `dev` sin alertas reales (`<n>` = 0 en P3, C1a y C1d) y C5 `2 → 3`, porque s0 ya
cuenta F (C3) y A2 (C4), vivas y activas hasta la limpieza.

Si en la copia local BE-2.3 no está «Hecho», P4 termina con 2: `--solo C1,C2,C3,C4` valida el resto (sin P4), y C5 se
repite cuando lo esté.

**En `local`** (no cierra el lote). Desde `BACKEND_FASTAPI/project` (sin comprobar todavía: Docker Desktop no arrancó
en la máquina donde se construyó; lo que sí se comprobó en local es el validador contra `ApiFalsa`, en
`tests/ops/test_validate33.py`, con la misma salida):

5. Levantar la base y la API con el código de la copia de trabajo y migrar (si `db` ya estaba en marcha, sigue igual):

```bash
docker compose up -d --build --wait db api
docker compose run --rm -T api python -m app.cli migrar
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/v1/alerts
```

Esperado: `Container campus-locator-backend-api-1 Healthy`, el evento `migracion_terminada` (con la base ya migrada,
`"aplicada": false` y `"admin_inicial": "ya_habia_admin"`) y `200`.

6. Lanzar el validador:

```bash
export VALIDACION_API_URL=http://localhost:8000/v1 VALIDACION_ADMIN_CORREO=admin@campus.edu.co
export VALIDACION_ADMIN_PASSWORD=local-solo-desarrollo-admin
uv run --group ops python src/ops/validate33.py --entorno local
```

Esperado (unos segundos): `[PASA]` en P2, P3, P4 (`GET /v1/admin/stats → 200`: en `local` no mira el PLAN) y en las
ocho comprobaciones, con los mismos detalles que en `dev` (P2 con `http://localhost:8000/v1`), `[LIMPIEZA] alertas de
prueba borradas: 4` y `== Resultado: pasa (código 0)`. Repetirlo da lo mismo.

7. Apagar lo que se levantó en el paso 5 (si `db` ya estaba en marcha antes, dejarla):

```bash
docker compose rm -sf api
docker compose ps --format '{{.Service}} {{.State}}'
```

Esperado: `api` ya no aparece (y `db running` si estaba antes; si no, `docker compose stop db`).
