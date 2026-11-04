# Validación 1-2 — BE-1.2 Base de datos y migraciones

| Campo | Valor |
|---|---|
| Lote | `BE-1.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate12.py` |
| Entornos | `dev`, `local` (ningún criterio depende de S3 ni SQS) |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple porque otro lote no está listo, el script termina con código 2 y el lote queda `Bloqueado`; si
falla por credenciales, permisos, herramientas o variables, con código 3 (infra §5.11). Se detiene en la primera que no
se cumple. En `dev` evalúa P1 a P4; en `local`, P2 y P5.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-1.1` en «Hecho»: `api` respondiendo | `GET /v1/health` → `200`; en `dev`, además, su `commit` es prefijo de la etiqueta de imagen del servicio `api` (`ecs describe-services` + `describe-task-definition`). La URL es `VALIDACION_API_URL` o, en `dev`, el output `api_base_url` + `/v1`; en `local`, sin `VALIDACION_API_URL`: código 3 |
| P3 | Solo `dev`: `INF-1.2` en «Hecho»: RDS y secretos | `rds describe-db-instances --db-instance-identifier campus-locator-dev-db` → `DBInstanceStatus = available` y `EngineVersion` ≥ 17.1; `secretsmanager describe-secret` de `campus-locator/dev/db` y `campus-locator/dev/admin-inicial` |
| P4 | Solo `dev`: tareas sueltas lanzables | `ecs describe-task-definition` de `campus-locator-dev-migrate` y `campus-locator-dev-validacion`; outputs `subredes_tareas` y `sg_migrate` en `terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -json` |
| P5 | Solo `local`: entorno levantado | `docker compose ps --format json` en `project/` muestra `db` y `api` en marcha (`State = running`) |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Toma la última revisión `ACTIVE` de `campus-locator-dev-migrate` y la lanza dos veces seguidas sin sobrescribir el comando (`python -m app.cli migrar`, como el paso 2 de `backend.yml`); la segunda empieza cuando la primera queda `STOPPED` | La revisión usa la misma imagen que el servicio `api`, las dos tareas terminan con `exitCode = 0` en el contenedor `app` y, si su log trae `migracion_terminada`, la segunda dice `aplicada = false` (no volvió a migrar). Con otro código, el detalle copia el motivo del log (`migracion_fallida`, `base_no_disponible` o `configuracion_incompleta`) |
| C2 | Tarea migrate (la misma revisión de C1) con comando `["python", "-m", "app.cli", "verificar-esquema"]` | `exitCode = 0`. Con `1` (difiere), el detalle copia hasta 10 eventos `esquema_diferencia` del log (`objeto aspecto (esperado → encontrado)`) y cuántos quedan; con `2` (no se pudo verificar), el motivo de `base_no_disponible` o `verificacion_fallida`: no se confunde con «difiere» (ARCHITECTURE §5.9) |
| C3 | SQL: `SELECT count(*) FROM usuarios WHERE rol = 'admin' AND activo AND correo = '<correo>'`, con la clave `correo` del secreto `campus-locator/dev/admin-inicial` en minúsculas (en `local`, `VALIDACION_ADMIN_CORREO`). El correo no se imprime | Devuelve `1` |
| C4 | `GET /v1/health/ready` | `200` con `"estado": "ok"` y `"db": "ok"`. Con `503`, el detalle da el `codigo` (`BASE_NO_DISPONIBLE`) |

**Tarea migrate** = `ecs run-task --cluster campus-locator-dev --launch-type FARGATE --task-definition
<revisión de C1>`, red `subredes_tareas` + `sg_migrate` con `assignPublicIp=ENABLED`, `startedBy = validate12` y, en
C2, `containerOverrides` sobre el contenedor `app`; luego `ecs wait tasks-stopped` (hasta 15 min), `exitCode` de
`ecs describe-tasks` y su log: `logs get-log-events` del stream `migrate/app/<id de la tarea>` en
`/campus-locator/dev/migrate`, con reintentos mientras el log no ha llegado. **SQL** = lo mismo con
`campus-locator-dev-validacion` y comando `["psql", "-tAc", "<consulta>"]`; la salida se lee del stream
`validacion/app/<id>` en `/campus-locator/dev/validacion` (infra §5.11). Las ayudas de tareas sueltas de
`src/ops/comun.py` hacen esto y las reutilizan los lotes siguientes (ARCHITECTURE §5.11, «Código común»). En `local`:
`docker compose run --rm -T api python -m app.cli …` y `docker compose exec -T db psql -U campus_app -d campus_locator
-tAc "<consulta>"`; en C1 se comparan dos ejecuciones de `migrar` (no hay revisión ni servicio).

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos. `migrar` es idempotente (§4.3): lanzarlo dos veces no cambia la base. Las tareas sueltas no dejan nada
salvo sus logs (14 días de retención). No hay restos posibles de ejecuciones anteriores.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate12.py --entorno dev
uv run --group ops python src/ops/validate12.py --entorno local   # con docker compose up en marcha
```

Variables: `AWS_PROFILE` (obligatoria en `dev`), `VALIDACION_API_URL` (opcional en `dev`, obligatoria en `local`) y
`VALIDACION_ADMIN_CORREO` (solo `local`, para C3; con el `docker-compose.yml` del repositorio,
`admin@campus.edu.co`); ver `ARCHITECTURE.md` §5.11. Duración aproximada: 6 minutos en `dev` (cuatro tareas sueltas),
1 minuto en `local`. El informe queda en `project/.validacion/BE-1.2-<fecha>.json` (o en `--informe RUTA`).

Herramientas: en `dev`, `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev` (outputs
`subredes_tareas`, `sg_migrate` y, sin `VALIDACION_API_URL`, `api_base_url`); en `local`, `docker compose`.

Antes de ejecutarlo:
- `AWS_PROFILE` tiene que estar definida aunque la CLI de AWS ya funcione con el perfil `default`: en ese caso,
  `export AWS_PROFILE=default`. Sin la variable, P1 termina con código 3.
- En `dev`, `backend.yml` tiene que haber terminado en verde en `main` con el código de BE-1.2: es el que registra la
  revisión de `migrate` con la imagen de `api` y ejecuta el primer `migrar`. Si aún no ha desplegado, C1 y C2 fallan
  con «`campus-locator-dev-migrate:N` usa `bootstrap` y `api` usa `<sha>`», C3 no encuentra la tabla `usuarios` y C4
  da `db = 'no_configurada'` (lo que responde la imagen de BE-1.1).
- En `local`: `docker compose up -d --build` en `project/`. El validador ejecuta `migrar` él mismo (C1).
