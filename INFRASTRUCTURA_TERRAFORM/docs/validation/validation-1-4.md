# Validación 1-4 — INF-1.4 Borde HTTPS (API Gateway)

| Campo | Valor |
|---|---|
| Lote | `INF-1.4` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate14.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P3 es de credenciales: código 3,
según §5.11).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.3` en «Hecho»: servicio `api` registrado en Cloud Map con SRV | `servicediscovery get-service` del servicio `api` del espacio `campus-locator.local` incluye un registro `SRV`; `ecs describe-services --cluster campus-locator-dev --services api` da `status = ACTIVE` |
| P2 | Output de la URL pública | `terraform -chdir=envs/dev output -json` contiene `api_base_url` con la forma `https://<id>.execute-api.us-east-1.amazonaws.com`, sin barra final |
| P3 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `apigatewayv2 get-apis` (la de nombre `campus-locator-dev-api`, cuyo `ApiEndpoint` = `api_base_url`), `apigatewayv2 get-routes`, `get-integrations` y `get-vpc-links` | Exactamente dos rutas, `ANY /{proxy+}` y `POST /v1/auth/login`, con `Target` a la misma integración `HTTP_PROXY`; `ConnectionType = VPC_LINK` hacia `campus-locator-dev-vpclink` (`VpcLinkStatus = AVAILABLE`, subredes públicas, grupo `campus-locator-dev-vpclink`); `IntegrationUri` = ARN del servicio Cloud Map `api` |
| C1b | Si `api` tiene `desiredCount = 0`, lo sube a 1 con `ecs update-service`, espera `services-stable` y que `servicediscovery discover-instances --namespace-name campus-locator.local --service-name api --health-status HEALTHY` lo devuelva. Hace `GET {api_base_url}/v1/health` con `httpx` desde la máquina de quien ejecuta (fuera de AWS), con reintentos durante 2 min, y guarda la cabecera `apigw-requestid` | Responde 200 por HTTPS con el certificado de AWS (verificación TLS activa) |
| C2a | `apigatewayv2 get-stage --api-id <id> --stage-name '$default'` | `AutoDeploy = true`; `RouteSettings` de `POST /v1/auth/login` con `ThrottlingRateLimit = 2` y `ThrottlingBurstLimit = 5`; la ruta general con 20 y 40 (en su `RouteSettings` o en `DefaultRouteSettings`) |
| C2b | Envía 100 `POST {api_base_url}/v1/auth/login` con cuerpo `{}` a 5 req/s durante 20 s (el cuerpo no llega a validar credenciales); espera 10 s y envía 100 `GET {api_base_url}/v1/health` a 10 req/s durante 10 s; cuenta los códigos | Al menos el 25 % de las peticiones a login reciben 429; las 100 de `/v1/health` responden 200 y ninguna 429 |
| C3a | `AccessLogSettings` de la etapa (`get-stage` de C2a) | `DestinationArn` = ARN del log group `/campus-locator/dev/apigw` |
| C3b | `logs filter-log-events --log-group-name /campus-locator/dev/apigw --start-time <inicio de C1b> --filter-pattern '{ $.requestId = "<apigw-requestid>" }'` cada 15 s, hasta 3 min | Aparece un evento JSON con el `requestId` de C1b y los campos del formato de ARCHITECTURE §5.10 (`routeKey = ANY /{proxy+}`, `status = 200`) |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos: las peticiones a login de C2b llevan cuerpo vacío y no crean usuarios ni sesiones, y `/v1/health` no
toca la base. Si `api` estaba en `desiredCount = 0`, lo devuelve a 0 al terminar (`ecs update-service
--desired-count 0`); si ya estaba en 1 no lo toca. Las líneas que generan las pruebas en `/campus-locator/dev/apigw` y
`/campus-locator/dev/api` caducan con la retención de 14 días (§5.10). No hay restos que buscar al empezar.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate14.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11). La región es `us-east-1` (§5.3). Ejecútese desde una red
fuera de AWS (C1b). Sirve con la imagen `bootstrap` o con la de BE-1.1. Duración aproximada: 3–5 min (hasta 10 si hay
que arrancar `api`).
