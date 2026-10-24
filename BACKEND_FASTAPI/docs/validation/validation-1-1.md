# Validación 1-1 — BE-1.1 Base del servicio

| Campo | Valor |
|---|---|
| Lote | `BE-1.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate11.py` |
| Entornos | `dev` (sin `local`: los tres criterios miran lo desplegado: `api_base_url`, CloudWatch, ECR y ECS) |
| Criterios | Automáticos: C1, C2, C3 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` con credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account = 648617469176`. Si falta o es otra cuenta: código 3 (credenciales), no 2 |
| P2 | `INF-1.3` en «Hecho»: clúster, servicio `api` y repositorio `campus-locator/backend` | `ecs describe-services --cluster campus-locator-dev --services api` → `status = ACTIVE`; `ecr describe-repositories --repository-names campus-locator/backend` sin error |
| P3 | `INF-1.4` en «Hecho»: HTTP API con su URL pública | `terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -json` contiene `api_base_url` (salvo que se pase `VALIDACION_API_URL`); `apigatewayv2 get-apis` incluye `campus-locator-dev-api` |
| P4 | Log group del proceso `api` | `logs describe-log-groups --log-group-name-prefix /campus-locator/dev/api` devuelve exactamente ese nombre |
| P5 | Historial de `main` disponible para C3 | `git fetch origin main` sin error |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Lee la imagen desplegada: `ecs describe-services` (`api`) → `taskDefinition` → `ecs describe-task-definition` → `image` del contenedor `app` (etiqueta = SHA). Luego `GET {api_base_url}/v1/health` | `200` con `{"estado": "ok", "version": …, "commit": …}` y el SHA de la etiqueta empieza por `commit` |
| C2a | `GET /v1/validacion-ruta-inexistente` con el encabezado `X-Request-Id: <uuid4 nuevo>` | `404`; el cuerpo solo tiene la clave `error`, con `codigo = "NO_ENCONTRADO"`, `mensaje` no vacío y `detalle` objeto o `null` (§5.1, §5.6); el encabezado `X-Request-Id` de la respuesta es el enviado |
| C2b | `logs filter-log-events --log-group-name /campus-locator/dev/api --start-time <inicio> --filter-pattern '{ $.request_id = "<uuid>" }'`, cada 10 s hasta 90 s | ≥ 1 evento, y cada uno es una línea JSON con `ts`, `nivel`, `proceso`, `request_id` y `evento` (§5.10) |
| C3a | Compara el SHA de C1 con `git log -1 --format=%H origin/main -- BACKEND_FASTAPI/project` | Son iguales: lo desplegado es el último commit de `main` que tocó `project/` |
| C3b | `ecr describe-images --repository-name campus-locator/backend --image-ids imageTag=<sha>` | La imagen existe con esa etiqueta (40 caracteres hexadecimales, infra §5.9) |
| C3c | `ecs describe-services` (`api`): despliegues y réplicas | Un solo despliegue `PRIMARY` con `rolloutState = COMPLETED` sobre la revisión de C1, y `runningCount = desiredCount = 1` |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos: solo hace lecturas y una petición a una ruta inexistente. No hay nada que borrar ni restos posibles de
ejecuciones anteriores.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate11.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria) y, opcional, `VALIDACION_API_URL` (`ARCHITECTURE.md` §5.11). No usa credenciales
de admin. Duración aproximada: 2 minutos.
