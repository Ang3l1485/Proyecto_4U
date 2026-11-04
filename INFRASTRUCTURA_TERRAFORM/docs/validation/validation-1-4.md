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

El script evalúa primero P3 (credenciales: código 3, según §5.11), luego P1 y P2 (código 2: el lote queda
`Bloqueado`); si una falla, no sigue. El output lo lee con `terraform -chdir=envs/dev output -json` (hace falta `init`
en esa copia); el resto, de las API de AWS.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.3` en «Hecho»: servicio `api` registrado en Cloud Map con SRV | `servicediscovery get-service` del servicio `api` del espacio `campus-locator.local` incluye un registro `SRV`; `ecs describe-services --cluster campus-locator-dev --services api` da `status = ACTIVE` |
| P2 | Output de la URL pública | `terraform -chdir=envs/dev output -json` contiene `api_base_url` con la forma `https://<id>.execute-api.us-east-1.amazonaws.com`, sin barra final |
| P3 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `apigatewayv2 get-apis` (la de nombre `campus-locator-dev-api`, cuyo `ApiEndpoint` = `api_base_url`), `apigatewayv2 get-routes`, `get-integrations` y `get-vpc-links` | Exactamente dos rutas, `ANY /{proxy+}` y `POST /v1/auth/login`, con `Target` a la misma integración `HTTP_PROXY`; `ConnectionType = VPC_LINK` hacia `campus-locator-dev-vpclink` (`VpcLinkStatus = AVAILABLE`, subredes públicas, grupo `campus-locator-dev-vpclink`); `IntegrationUri` = ARN del servicio Cloud Map `api` |
| C1b | Si `api` tiene `desiredCount = 0`, comprueba que existe `campus-locator/backend:bootstrap`, lo sube a 1 con `ecs update-service`, espera `services-stable`, una tarea `HEALTHY` (hasta 5 min) y que `servicediscovery discover-instances --namespace-name campus-locator.local --service-name api --health-status HEALTHY` lo devuelva. Hace `GET {api_base_url}/v1/health` con `httpx` desde la máquina de quien ejecuta (fuera de AWS), con reintentos durante 2 min, y guarda la cabecera `apigw-requestid` | Responde 200 por HTTPS con el certificado de AWS (verificación TLS activa) |
| C2a | `apigatewayv2 get-stage --api-id <id> --stage-name '$default'` | `AutoDeploy = true`; `RouteSettings` de `POST /v1/auth/login` con `ThrottlingRateLimit = 2` y `ThrottlingBurstLimit = 5`; la ruta general con 20 y 40 (en su `RouteSettings` o en `DefaultRouteSettings`) |
| C2b | Envía 200 `POST {api_base_url}/v1/auth/login` con cuerpo `{}` a 20 req/s durante 10 s (el cuerpo no llega a validar credenciales); espera 10 s y envía 100 `GET {api_base_url}/v1/health` a 10 req/s durante 10 s; cuenta los códigos | Al menos el 10 % de las peticiones a login (20 de 200) reciben 429; las 100 de `/v1/health` responden 200 y ninguna 429 |
| C3a | `AccessLogSettings` de la etapa (`get-stage` de C2a) y `logs describe-log-groups` | `DestinationArn` = ARN del log group `/campus-locator/dev/apigw` (sin el `:*` final que añade `describe-log-groups`), retención 14 días, y `Format` es un objeto JSON con exactamente los diez campos de §5.10 y `requestId = $context.requestId` |
| C3b | `logs filter-log-events --log-group-name /campus-locator/dev/apigw --start-time <inicio de C1b> --filter-pattern '{ $.requestId = "<apigw-requestid>" }'` cada 15 s, hasta 3 min | Aparece un evento JSON con el `requestId` de C1b y los diez campos del formato de ARCHITECTURE §5.10 (`routeKey = ANY /{proxy+}`, `status = "200"`: todos los valores son cadenas) |

`--solo` admite los alias `C1`, `C2` y `C3`. C1b, C2b y C3b comparten el encendido de `api`: se sube a 1 una sola vez
por ejecución. Si C1b se excluye con `--solo` o falla, C3b hace su propia petición a `/v1/health`. C2b envía las
peticiones a ritmo constante en paralelo (la latencia desde Colombia no frena el ritmo). API Gateway aplica el
*throttling* de forma aproximada (ARCHITECTURE §3.3): a 5 req/s, como pedía la primera versión de C2b, solo 1 de 100
recibió 429. Medido el 2026-10-24 contra login: 23 % de 429 a 10 req/s, 34 % a 20 y 57 % a 50; C2b usa 20 req/s y
exige el 10 %, con margen. Las que no son 429 dan **501** con la imagen `bootstrap` (`http.server` no implementa POST)
y 422 con la de BE-1.1. El script no imprime cuerpos de respuesta.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos: las peticiones a login de C2b llevan cuerpo vacío y no crean usuarios ni sesiones, y `/v1/health` no
toca la base. Si `api` estaba en `desiredCount = 0`, lo devuelve a 0 al terminar (`ecs update-service
--desired-count 0`); si ya estaba en 1 no lo toca. Las líneas que generan las pruebas en `/campus-locator/dev/apigw` y
`/campus-locator/dev/api` caducan con la retención de 14 días (§5.10). No hay restos que buscar al empezar.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con lectura del bucket de estado (`terraform output`);
`ecs:DescribeServices`, `UpdateService`, `ListTasks` y `DescribeTasks` sobre `campus-locator-dev`; `ecr:DescribeImages`;
lectura de Cloud Map, EC2, API Gateway (`apigateway:GET`) y `logs:DescribeLogGroups` y `FilterLogEvents` sobre
`/campus-locator/dev/apigw`; para el paso 4 de la preparación, sesión de `gh` de la cuenta dueña del repositorio,
revisora del entorno `dev`. La región es `us-east-1` (§5.3). Los comandos van desde la raíz del repositorio, con
`export AWS_REGION=us-east-1`.

**Preparación** (una sola vez, al cerrar el lote). El validador comprueba los recursos **después** del `apply` desde
`main`: sin él termina con código 2 (P2: `INF-1.4 no está aplicado en envs/dev: falta el output api_base_url`).

1. Comprobar que ningún nombre del lote está ocupado (restos de un intento anterior, R11) y si existe el rol vinculado
   de API Gateway:
   ```bash
   aws apigatewayv2 get-apis --query "Items[?starts_with(Name,'campus-locator')].[Name,ApiId]" --output text
   aws apigatewayv2 get-vpc-links --query "Items[?starts_with(Name,'campus-locator')].[Name,VpcLinkId]" --output text
   aws logs describe-log-groups --log-group-name-prefix /campus-locator/dev/apigw --query 'logGroups[].logGroupName' \
     --output text
   aws iam get-role --role-name AWSServiceRoleForAPIGateway --query Role.Arn --output text 2>&1 | tail -1
   ```
   Esperado: los tres primeros no imprimen nada (las API `ta-*` del otro proyecto no empiezan por `campus-locator`). El
   último imprime `arn:aws:iam::648617469176:role/aws-service-role/ops.apigateway.amazonaws.com/AWSServiceRoleForAPIGateway`
   o `… (NoSuchEntity) …`: en ese caso lo crea el `apply` al crear el VPC Link (`PowerUserAccess` de `gha-terraform`
   incluye `iam:CreateServiceLinkedRole`). Si aparece cualquiera de los nombres de §5.1 del lote, parar y revisarlo
   antes de seguir.
2. Comprobaciones locales y `plan` (este lote no añade proveedores: el lock no cambia):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|^  \+ api_base_url|will be (updated|destroyed|replaced)'
   git diff --exit-code envs/dev/.terraform.lock.hcl && echo LOCK_SIN_CAMBIOS
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 7 to add, 0 to change, 0 to destroy.`,
   `+ api_base_url = (known after apply)` y `LOCK_SIN_CAMBIOS`; ninguna línea `will be updated`, `destroyed` ni
   `replaced` (ningún recurso existente cambia). Un *push* directo a `main` no tiene `plan` en un PR (§3.9): este es el
   que revisa quien aprueba el paso 4.
3. Commit y *push* a `main` del módulo, `computo` (output nuevo), `envs/dev`, el validador y `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/borde INFRASTRUCTURA_TERRAFORM/project/modules/computo \
     INFRASTRUCTURA_TERRAFORM/project/envs/dev INFRASTRUCTURA_TERRAFORM/project/src/ops/validate14.py \
     INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-1.4: borde HTTPS"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/` ni `.validacion/`. En GitHub arranca `infra.yml`
   y su job `apply (main)` queda esperando la aprobación del entorno `dev` (si hay otra ejecución de `main` de un
   commit anterior esperando, retiene la fila: cancelarla).
4. Aprobar el `apply`: igual que el paso 4 de [`validation-1-1`](./validation-1-1.md) §5, con `comment="INF-1.4"`.
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 7 added, 0 changed, 0 destroyed.`
   El VPC Link tarda unos minutos en quedar `AVAILABLE`; Terraform lo espera.
5. Comprobar que no quedan diferencias (un formato de *access logs* o un *throttling* que AWS normaliza distinto daría
   cambios en cada `plan`):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -detailed-exitcode -no-color | grep -E '^(No changes|Plan:)'
   echo "codigo=${PIPESTATUS[0]}"
   terraform -chdir=envs/dev output -raw api_base_url; echo
   cd ../..
   ```
   Esperado: `No changes. Your infrastructure matches the configuration.`, `codigo=0` y
   `https://<id>.execute-api.us-east-1.amazonaws.com` (sin barra final).

Este lote no añade variables al repositorio de GitHub (§5.9): `api_base_url` lo usa la app (`ApiConfig.kt`).

**Ejecución** (desde una red fuera de AWS, por C1b):

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate14.py --entorno dev
```

Esperado: `[PASA]` en P3, P1, P2, C1a, C1b, C2a, C2b, C3a y C3b y `Resultado: pasa (código 0)`; en stderr,
`limpieza hecha: devolver el servicio api a 0 réplicas` si estaba en 0. C2b imprime algo como
`login {'501': 132, '429': 68}; /v1/health {'200': 100}`. Sirve con la imagen `bootstrap` o con la de BE-1.1. Duración
aproximada: 5–8 min (hasta 12 si hay que arrancar `api`).
