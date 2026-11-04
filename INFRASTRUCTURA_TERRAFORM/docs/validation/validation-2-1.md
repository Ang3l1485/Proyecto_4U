# Validación 2-1 — INF-2.1 Encendido de `embedding` y escalado del `worker`

| Campo | Valor |
|---|---|
| Lote | `INF-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1 (C1a, C1b), C2 (C2a), C3 (C3a) · Opcionales, no cierran el lote: C2b, C3b, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11. El diseño que se valida está en ARCHITECTURE §3.4, §5.10 (contrato de encendido), ADR-INF-14
y ADR-INF-15: `embedding` apagado por defecto, encendido manual y apagado automático; `worker` por cola, solo con
`embedding` encendido.

**Desde 0.13.1 el lote se cierra con C1a, C1b, C2a y C3a (~8 min)**: encender y apagar en `dev`, y la configuración del
apagado automático y del escalado (PLAN INF-2.1). C2b, C3b y C4 observan ese comportamiento en `dev` (~1,5 h, casi todo
la espera de 45 min de C2b) y son opcionales: no cierran el lote. C1a ya ejercita parte del apagado: encender espera a
que la alarma de inactividad, en `ALARM` mientras nadie usa el sistema, vea `EmbeddingEncendidos`.

## 1. Precondiciones

El script evalúa primero P4 y P5 (credenciales y uso: código 3, según §5.11) y luego P1–P3 (código 2: el lote queda
`Bloqueado`); si una falla, no sigue. Los outputs los lee con `terraform -chdir=envs/dev output -json` (hace falta `init`
en esa copia); el resto, de las API de AWS.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.3` en «Hecho»: servicios `worker` y `embedding` | `ecs describe-services --cluster campus-locator-dev --services worker embedding` devuelve los dos con `status = ACTIVE` |
| P2 | `INF-1.4` en «Hecho»: *access logs* de la API (de ellos sale la métrica de uso de `/v1/localize`) | `logs describe-log-groups --log-group-name-prefix /campus-locator/dev/apigw` devuelve el grupo y el output `api_base_url` existe |
| P3 | Outputs que usa el script | `terraform -chdir=envs/dev output -json` contiene `ecs_cluster` (= `campus-locator-dev`), `ecs_servicios`, `sqs_ingesta_url` y `sqs_purga_url` |
| P4 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |
| P5 | Lejos del apagado de las 22:00 y con los servicios libres | Si se incluye C2b, C3b o C4 (la ejecución dura 1,5–2 h), la hora de Bogotá (`zoneinfo`; sin base de zonas, UTC−5) está entre 06:00 y 19:30; si solo se incluye C1, antes de las 21:40. Si se incluye alguna comprobación que cambia algo (C1a, C1b, C3b, C2b o C4), `embedding` y `worker` tienen `desiredCount` y `runningCount` en 0 (si no, alguien los está usando: código 3 con ese detalle) |

## 2. Comprobaciones automáticas

Orden: C2a, C3a, C1a, C1b, C3b, C2b, C4 (las tres últimas, opcionales). El script enciende y apaga con la clase `Operador` de `src/ops/embedding.py`
(contrato de §5.10), no con comandos propios. Los mensajes de prueba tienen la forma de `s3:TestEvent` (el `worker`
real los borra sin hacer nada, `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.8) y `RequestId =
validacion-2-1-<AAAAMMDD-HHMMSS>-<n>`.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C2a | `logs describe-metric-filters --log-group-name /campus-locator/dev/apigw` y `logs test-metric-filter` con cinco líneas de *access log* del formato de §5.10 (`POST /v1/localize`, `GET /v1/localize`, `POST /v1/auth/login`, `POST /v1/localize/x` y `PUT /v1/localize`); `cloudwatch describe-alarms` de `campus-locator-dev-embedding-inactivo`; `application-autoscaling describe-scaling-policies` de `campus-locator-dev-embedding-apagar`, `describe-scalable-targets` y `describe-scheduled-actions` de los dos servicios; lee `apagado_embedding` de `envs/dev/terraform.tfvars` | El filtro `campus-locator-dev-localize` publica `LocalizePeticiones` = 1 en `campus-locator/dev` y solo casa con la línea de `POST /v1/localize`. La alarma es `LessThanThreshold` 0,5 en `inactividad_min` de `inactividad_min` periodos (45 de 45), con métricas de 60 s (`LocalizePeticiones`, `EmbeddingEncendidos`, visibles y en vuelo de `ingesta` y `purga`, y `CPUUtilization` de `embedding`), todas usadas en la expresión, y su única acción es la política, que es `StepScaling` `ExactCapacity` con dos pasos, `(−∞, 0]` y `[0, ∞)`, los dos → 0, y agregación `Minimum`. Existen los objetivos escalables de `embedding` y `worker`, y `campus-locator-dev-embedding-apagar-noche` y `campus-locator-dev-worker-apagar-noche` con el `Schedule` y la `Timezone` de `terraform.tfvars` (`cron(0 22 * * ? *)`, `America/Bogota`) y rango 0-0 (falla si `noche = null`) |
| C3a | `describe-alarms` de `campus-locator-dev-worker-cola-ingesta`, `-worker-cola-purga` y `-worker-colas-vacias`; `describe-scaling-policies` de `campus-locator-dev-worker-cola` y `-worker-colas-vacias` | Las dos de subida son `GreaterThanThreshold` 0,5 en 1 de 10 periodos, con los visibles de su cola y la `CPUUtilization` de `embedding` unidos con `AND` en la expresión, y su acción es `worker-cola` (pasos `(−∞, 0]` y `[0, ∞)`, los dos → 1, `Maximum`). La de bajada es `LessThanThreshold` 0,5 en 15 de 15, con visibles y en vuelo de las dos colas y la `CPUUtilization` de `worker`, y su acción es `worker-colas-vacias` (los dos pasos → 0, `Minimum`) |
| C1a | `embedding.py encender`: rango 0-1 en los dos objetivos, muestra de `EmbeddingEncendidos`, espera a que la alarma de inactividad la vea y no esté en `ALARM`, `embedding` a 1; sondea cada 15 s `ecs describe-services`, `ecs describe-tasks` y `servicediscovery discover-instances --namespace-name campus-locator.local --service-name embedding` | En ≤ 10 min desde el encendido: `runningCount = 1`, despliegue `COMPLETED`, tarea `HEALTHY` e instancia sana en Cloud Map; rango 0-1 en los dos. El detalle incluye el tiempo |
| C1b | `embedding.py apagar`; sondea los servicios cada 15 s (máx. 10 min) | `embedding` con `desiredCount = runningCount = 0`, `worker` con `desiredCount = 0` y rango 0-0 en los dos |
| C3b (opcional) | Enciende `embedding` como C1a. Comprueba que `ingesta` y `purga` están vacías (visibles, en vuelo y retrasados en 0) y `worker` en 0; envía 3 mensajes a `ingesta`; sondea `worker` cada 30 s (máx. 20 min). Cuando sube, borra sus mensajes (la imagen `bootstrap` no consume las colas), anota cuándo borró el último, espera a que las dos colas cuenten 0 (los contadores de SQS tardan hasta ~1 min) y sondea cada 30 s (máx. 35 min); al bajar, lee `application-autoscaling describe-scaling-activities` de `worker` | `desiredCount` de `worker` pasa a 1 (con una actividad cuya `Cause` cita la alarma de `ingesta` o `worker-cola`) y vuelve a 0 entre 12 y 30 min después de borrar el último mensaje propio, con una actividad cuya `Cause` cita `worker-colas-vacias` (actividades `Pending`, `InProgress` o `Successful`: ECS tarda ~30 s en darlas por cumplidas; si no aparece, la busca 3 min más). Se mira `desiredCount`, no `runningCount`. Si hay mensajes ajenos en las colas, falla con ese detalle (el `worker` de prueba no los vaciaría) |
| C2b (opcional) | Deja `embedding` encendido (de C3b; si no lo está, lo enciende) sin peticiones a `/v1/localize` ni mensajes en las colas. Referencia: el último uso, el más tardío entre el borrado del último mensaje propio (C3b, o el propio C2b si C3b dejó mensajes) y la muestra de `EmbeddingEncendidos` del último encendido. Sondea cada minuto (máx. 70 min desde la referencia) `ecs describe-services` y `describe-scaling-activities` de `embedding` | `embedding` queda en `desiredCount = 0` por una actividad (`Pending`, `InProgress` o `Successful`) cuya `Cause` cita `embedding-inactivo` o `embedding-apagar`, entre 43 y 60 min después de la referencia (43 y no 45: el minuto en que se vacían las colas aún cuenta como uso y la alarma rellena con 0 el último minuto sin dato, ARCHITECTURE §3.4). Si queda en 0 por otra causa, falla con las causas que ve; si no se apaga, con el estado de la alarma y las `LocalizePeticiones` del intervalo |
| C4 (opcional) | Parte de `embedding` apagado por C2b, con el rango de `worker` en 0-1 como lo deja el apagado por inactividad (si `embedding` sigue en 1, lo pone en 0 como la política; si el rango de `worker` es 0-0, lo pone en 0-1; el detalle lo dice). Espera a que `embedding` no tenga tareas y a que su `CPUUtilization` lleve ≥ 3 min sin muestras (`cloudwatch get-metric-statistics`); comprueba colas vacías; envía 3 mensajes; espera (máx. 15 min) a que `get-metric-statistics` de `ApproximateNumberOfMessagesVisible` de `ingesta` muestre ≥ 1 desde el minuto del envío (la alarma ya los pudo ver), observa 5 min más y borra sus mensajes | `desiredCount` de `worker` sigue en 0 todo el intervalo, `cloudwatch describe-alarm-history` de `campus-locator-dev-worker-cola-ingesta` no tiene ningún paso a `ALARM` desde el envío y `describe-scaling-activities` de `worker` no registra ninguna subida a 1 |

`--solo` admite los alias `C1` (C1a y C1b), `C2` (C2a y C2b) y `C3` (C3a y C3b). Cada comprobación de comportamiento
prepara lo que necesita si se ejecuta sola (C2b enciende; C4 deja `worker` en 0-1). Con solo C2a y C3a no cambia nada.
Los plazos tienen margen para el retraso con que SQS y ECS publican sus métricas (ARCHITECTURE §3.4): el script se
probó en local contra una simulación de AWS con 2 a 8 min de retraso.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Con el cierre del lote (`--solo C1,C2a,C3a`) no crea mensajes: solo enciende y apaga `embedding`, y al terminar lo
deja apagado. Las opcionales crean 6 mensajes en `ingesta` (3 en C3b y 3 en C4) con la forma de `s3:TestEvent` y `RequestId` que empieza por
`validacion-2-1-`, y los borra él mismo (`sqs receive-message` + `delete-message-batch`) en cuanto la comprobación ya no
los necesita; si el `worker` real los recibe antes, los borra él. Los ajenos que reciba vuelven a la cola enseguida
(`change-message-visibility-batch` con visibilidad 0). Solo lee la cola mientras le quedan mensajes propios sin borrar
(y como mucho 3 veces por comprobación), porque cada lectura suma una recepción a los ajenos (`maxReceiveCount = 5`,
§5.6). Al empezar, si `ingesta` tiene entre 1 y 10 mensajes visibles y ninguno en vuelo, borra los `validacion-2-1-` de
ejecuciones anteriores con más de 15 min (una lectura). En la limpieza, siempre: borra los mensajes propios que queden y
deja `embedding` y `worker` apagados con `embedding.py apagar` (rango 0-0 y `desiredCount = 0`), que es como lo exige P5
al empezar. Nunca cambia `desiredCount` de `worker` salvo con `embedding.py apagar`; en C4 solo su rango. No toca el
filtro, las alarmas, las políticas ni las acciones. `embedding` queda encendido unos 5 min en el cierre y ~1–1,25 h
con las opcionales (~0,13 USD).
Las paradas por escalado tienen `stopCode = ServiceSchedulerInitiated` y no avisan aunque INF-3.1 esté aplicado (§3.8).

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con lectura del bucket de estado (`terraform output`);
`ecs:DescribeServices`, `UpdateService`, `ListTasks` y `DescribeTasks` sobre `campus-locator-dev`;
`application-autoscaling:Describe*` y `RegisterScalableTarget`; `cloudwatch:DescribeAlarms`, `DescribeAlarmHistory`,
`GetMetricStatistics` y `PutMetricData`; `logs:DescribeLogGroups`, `DescribeMetricFilters` y `TestMetricFilter`;
`servicediscovery:DiscoverInstances`; `sqs:GetQueueUrl` y `GetQueueAttributes` en `ingesta` y `purga`, y `SendMessage`,
`ReceiveMessage`, `DeleteMessage` y `ChangeMessageVisibility` en `ingesta`; para el paso 1 de la preparación,
`iam:CreateServiceLinkedRole`; para el paso 4, sesión de `gh` de la cuenta dueña del repositorio, revisora del entorno
`dev`. La región es `us-east-1` (§5.3). Los comandos van desde la raíz del repositorio, con
`export AWS_REGION=us-east-1`.

**Preparación** (una sola vez, al cerrar el lote). El validador comprueba los recursos **después** del `apply` desde
`main`: sin él, C2a y C3a fallan (`no existe la política …`) y C1a con `INF-2.1 no está aplicado: falta el objetivo
escalable de embedding`.

1. Comprobar que ningún nombre del lote está ocupado y crear, si falta, el rol vinculado de Application Auto Scaling
   para ECS (§3.1):
   ```bash
   aws application-autoscaling describe-scalable-targets --service-namespace ecs \
     --query "ScalableTargets[?starts_with(ResourceId,'service/campus-locator-dev/')].ResourceId" --output text
   aws cloudwatch describe-alarms --alarm-name-prefix campus-locator-dev- --query 'MetricAlarms[].AlarmName' --output text
   aws logs describe-metric-filters --log-group-name /campus-locator/dev/apigw --query 'metricFilters[].filterName' \
     --output text
   aws iam get-role --role-name AWSServiceRoleForApplicationAutoScaling_ECSService --query Role.Arn --output text 2>&1 \
     | tail -1
   ```
   Esperado: los tres primeros no imprimen nada; el último, el ARN del rol o `… (NoSuchEntity) …`. Si aparece
   cualquiera de los nombres de §5.1 del lote, parar y revisarlo antes de seguir. Con `NoSuchEntity`:
   ```bash
   aws iam create-service-linked-role --aws-service-name ecs.application-autoscaling.amazonaws.com \
     --query Role.Arn --output text
   ```
   Esperado: `arn:aws:iam::648617469176:role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService`.
2. Comprobaciones locales y `plan` (este lote no añade proveedores: el lock no cambia):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|will be (updated|destroyed|replaced)'
   git diff --exit-code envs/dev/.terraform.lock.hcl && echo LOCK_SIN_CAMBIOS
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 12 to add, 0 to change, 0 to destroy.` (11 en
   `computo` y el filtro de `borde`; ningún output nuevo) y `LOCK_SIN_CAMBIOS`; ninguna línea `will be updated`,
   `destroyed` ni `replaced`. Un *push* directo a `main` no tiene `plan` en un PR (§3.9): este es el que revisa quien
   aprueba el paso 4.
3. Commit y *push* a `main` de `borde`, `computo`, `envs/dev`, `embedding.py`, el validador y `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/borde INFRASTRUCTURA_TERRAFORM/project/modules/computo \
     INFRASTRUCTURA_TERRAFORM/project/envs/dev INFRASTRUCTURA_TERRAFORM/project/src/ops/embedding.py \
     INFRASTRUCTURA_TERRAFORM/project/src/ops/validate21.py INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-2.1: encendido de embedding y escalado del worker"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/` ni `.validacion/`, ni nada de esta carpeta sin
   añadir. En GitHub arranca `infra.yml` y su job `apply (main)` queda esperando la aprobación del entorno `dev` (si
   hay otra ejecución de `main` de un commit anterior esperando, retiene la fila: cancelarla).
4. Aprobar el `apply`: igual que el paso 4 de [`validation-1-1`](./validation-1-1.md) §5, con `comment="INF-2.1"`.
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 12 added, 0 changed, 0 destroyed.`
5. Comprobar que no quedan diferencias (una alarma de expresión, un paso de política o una acción programada que AWS
   normaliza distinto daría cambios en cada `plan`) y ver el estado inicial:
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -detailed-exitcode -no-color | grep -E '^(No changes|Plan:)'
   echo "codigo=${PIPESTATUS[0]}"
   uv run --group ops python src/ops/embedding.py estado
   cd ../..
   ```
   Esperado: `No changes. Your infrastructure matches the configuration.`, `codigo=0` y, de `embedding.py estado`,
   `embedding: apagado · deseadas 0, en marcha 0, pendientes 0 · rango 0-0`, lo mismo para `worker` (`en 0`), una
   línea por alarma (cualquier estado: recién creadas pueden estar en `INSUFFICIENT_DATA`), las dos colas y las dos
   acciones `cron(0 22 * * ? *) America/Bogota`.

Este lote no añade outputs ni variables del repositorio de GitHub (§5.9).

**Ejecución para cerrar el lote** (C1, C2a y C3a; empezar antes de las 21:40 de Bogotá, P5; ~8 min). Mientras corre,
nadie debe usar `embedding.py` ni desplegar `embedding` (`embedding.yml`):

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate21.py --entorno dev --solo C1,C2a,C3a
```

Esperado: `[PASA]` en P4, P5, P1, P2, P3, C2a, C3a, C1a y C1b; `[OMITIDA]` en C3b, C2b y C4; `Resultado: pasa (código
0)`; en stderr, `limpieza hecha: dejar embedding y worker apagados (embedding.py apagar)`. C1a da el tiempo (por
ejemplo, `sano en 4.8 min …`).

**Ejecución completa (opcional)**: sin `--solo`, empezando entre las 06:00 y las 19:30 de Bogotá (P5); dura 1,5–2 h y
la acción de las 22:00 apagaría `embedding` a mitad. Mientras corre, además, nadie debe llamar a `POST /v1/localize`
(retrasa el apagado de C2b) ni subir fotos al dataset (los mensajes ajenos hacen fallar C3b, C2b y C4). Esperado:
`[PASA]` también en C3b, C2b y C4, con detalles como `C3b worker 0 → 1 a los 3.0 min de enviar 3 mensajes; 1 → 0 a
los 16.0 min de vaciarse las colas …` y `C2b embedding → 0 a los 46.0 min sin uso …`. Si se interrumpe con Ctrl+C,
la limpieza borra los mensajes y apaga `embedding` igual.
