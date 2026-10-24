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

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-1.1` en «Hecho»: `api` desplegada y respondiendo | `GET /v1/health` → `200` y su `commit` es prefijo de la etiqueta de imagen del servicio `api` (`ecs describe-services` + `describe-task-definition`) |
| P3 | `INF-1.2` en «Hecho»: RDS y secretos | `rds describe-db-instances --db-instance-identifier campus-locator-dev-db` → `DBInstanceStatus = available` y `EngineVersion` ≥ 17.1; `secretsmanager describe-secret` de `campus-locator/dev/db` y `campus-locator/dev/admin-inicial` |
| P4 | Solo `dev`: tareas sueltas lanzables | `ecs describe-task-definition` de `campus-locator-dev-migrate` y `campus-locator-dev-validacion`; outputs `subredes_tareas` y `sg_migrate` en `terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -json` |
| P5 | Solo `local`: entorno levantado | `docker compose ps` en `project/` muestra los servicios en marcha; `VALIDACION_API_URL` definida |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Toma la última revisión `ACTIVE` de `campus-locator-dev-migrate` y la lanza dos veces seguidas sin sobrescribir el comando (`python -m app.cli migrar`, como el paso 2 de `backend.yml`); la segunda empieza cuando la primera queda `STOPPED` | La revisión usa la misma imagen que el servicio `api` y las dos tareas terminan con `exitCode = 0` en el contenedor `app` |
| C2 | Tarea migrate con comando `["python", "-m", "app.cli", "verificar-esquema"]` | `exitCode = 0`. Con `1`, el detalle copia las diferencias que la tarea imprimió en `/campus-locator/dev/migrate` |
| C3 | SQL: `SELECT count(*) FROM usuarios WHERE rol = 'admin' AND activo AND correo = '<correo>'`, con la clave `correo` del secreto `campus-locator/dev/admin-inicial` (en `local`, `VALIDACION_ADMIN_CORREO`) | Devuelve `1` |
| C4 | `GET /v1/health/ready` | `200` con `"estado": "ok"` y `"db": "ok"` |

**Tarea migrate** = `ecs run-task --cluster campus-locator-dev --launch-type FARGATE --task-definition
campus-locator-dev-migrate`, red `subredes_tareas` + `sg_migrate` con `assignPublicIp=ENABLED` y `containerOverrides`
sobre el contenedor `app`; luego `ecs wait tasks-stopped` y `exitCode` de `ecs describe-tasks`. **SQL** = lo mismo con
`campus-locator-dev-validacion` y comando `["psql", "-tAc", "<consulta>"]`; la salida se lee del stream de esa tarea en
`/campus-locator/dev/validacion` (infra §5.11). En `local`: `docker compose run --rm api python -m app.cli …` y `psql`
contra la base del compose; en C1 se comparan dos ejecuciones de `migrar` (no hay revisión ni servicio).

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
`VALIDACION_ADMIN_CORREO` (solo `local`, para C3); ver `ARCHITECTURE.md` §5.11. Duración aproximada: 6 minutos en `dev`
(cuatro tareas sueltas), 1 minuto en `local`.
