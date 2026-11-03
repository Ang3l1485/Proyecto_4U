# Validación 3-1 — INF-3.1 Observabilidad y alarmas

| Campo | Valor |
|---|---|
| Lote | `INF-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate31.py` (pruebas: `project/tests/ops/test_validate31.py`) |
| Entornos | `dev` |
| Criterios | Automáticos: C1 (C1a, C1b, C1c), C2 (C2a), C3 (C3a, C3b) · Manuales: C2b, C3c (los correos) |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11. El diseño que se valida está en ARCHITECTURE §3.8, §5.6 (política del topic), §5.10
(parámetros exactos de las alarmas y patrón de la regla) y ADR-INF-16.

El script **no toca los servicios** `api`, `worker` ni `embedding` (ni los enciende ni los detiene): C2 deja un mensaje
marcado en una DLQ vacía y lo borra; C3 lanza una tarea suelta de la definición de validación que sale con error.
Dura **10–30 min** (C3 ~5 min; C2, de 3 a 20 min según cuánto tarde SQS en publicar la métrica de una DLQ inactiva,
ARCHITECTURE §3.4; con todo al límite, ~1 h) y cuesta **menos de 0,01 USD** (§3.10). No tiene hora límite: no necesita
`embedding`.

## 1. Precondiciones

El script evalúa P4 (credenciales: código 3, según §5.11) y luego P1, P2 y P3 (código 2: el lote queda `Bloqueado`);
si una falla, no sigue. Los outputs los lee con `terraform -chdir=envs/dev output -json` (hace falta `init` en esa
copia); el resto, de las API de AWS.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.4` en «Hecho»: HTTP API creada (su `ApiId` es la dimensión de la alarma de 5xx) | `apigatewayv2 get-apis` contiene `campus-locator-dev-api` |
| P2 | `INF-2.1` en «Hecho»: apagado automático de `embedding` aplicado | `application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id service/campus-locator-dev/embedding` devuelve `campus-locator-dev-embedding-apagar-noche` |
| P3 | INF-3.1 aplicado y outputs que usa el script | `terraform -chdir=envs/dev output -json` contiene `sns_alertas_arn` (si falta: `INF-3.1 no está aplicado en envs/dev`, como `validate14.py` con su output), `api_base_url` (= el `ApiEndpoint` de P1), `ecs_cluster` (= `campus-locator-dev`), `familias_tarea` (con `validacion`), `subredes_tareas`, `sg_migrate`, `sqs_ingesta_dlq_url` y `sqs_purga_dlq_url` (que terminan en el nombre de su DLQ) |
| P4 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

## 2. Comprobaciones automáticas

Orden: C1a, C1b, C1c, C3a, C3b, C2a (C3 antes que C2 porque tarda menos). Los nombres y parámetros esperados son los de
ARCHITECTURE §5.1 y §5.10; el script los tiene en `alarmas_esperadas` y `patron_esperado` (cambiar uno es cambiar los
dos, §5.10).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `cloudwatch describe-alarms --alarm-names` con los seis nombres de alarma de §5.1 | Existen las seis y cada una tiene exactamente el espacio, la métrica, las dimensiones, la estadística, el periodo, los periodos (`EvaluationPeriods` y `DatapointsToAlarm`), la comparación, el umbral y `TreatMissingData = notBreaching` de la tabla de §5.10 (la de 5xx con el `ApiId` de P1), con `ActionsEnabled` y `AlarmActions` que incluye `sns_alertas_arn`. El detalle da el estado de cada una. Las alarmas de escalado de INF-2.1 no cuentan ni estorban |
| C1b | `events describe-rule --name campus-locator-dev-tarea-detenida`; `events test-event-pattern` del patrón guardado con los 9 eventos sintéticos de `CASOS_PATRON` (ARCHITECTURE §5.12; sin efectos); `events list-targets-by-rule` y `sns get-topic-attributes` | La regla está `ENABLED` y su `EventPattern` es el de §5.10 (`source = aws.ecs`, `detail-type = ECS Task State Change`, el `clusterArn` de `campus-locator-dev`, `lastStatus = STOPPED`, `stopCode` ∈ {`EssentialContainerExited`, `TaskFailedToStart`} y `$or` de `group` ∈ {`service:api`, `service:embedding`, `service:worker`} o `startedBy = validacion-3-1`; las listas se comparan sin orden); `TestEventPattern` da lo esperado en los 9 casos (avisan los servicios que terminan o no arrancan y la tarea de prueba; no avisan `migrate` que sale con 0, la tarea de validación de otro validador, `ServiceSchedulerInitiated`, otro clúster ni un `lastStatus` distinto de `STOPPED`; si no, el detalle dice cuál); su único destino es `sns_alertas_arn`; la `Policy` del topic deja hacer `sns:Publish` a `events.amazonaws.com` con una condición que nombra el ARN de la regla, y a `cloudwatch.amazonaws.com` o a la cuenta (declaración `AWS: *` con `AWS:SourceOwner` = la cuenta) |
| C1c | `sns list-subscriptions-by-topic --topic-arn <sns_alertas_arn>` y `sns get-subscription-attributes`; lee `correo_alertas` de `envs/dev/terraform.tfvars` | Hay una suscripción `email` a `correo_alertas` (sin distinguir mayúsculas), su `SubscriptionArn` no es `PendingConfirmation` y `PendingConfirmation = false`. El correo sale enmascarado (`fr…@gmail.com`) en la salida y en el informe |
| C3a | Lanza una tarea suelta con `ecs run-task`: definición `familias_tarea.validacion` (`postgres:17-alpine`), Fargate, red `subredes_tareas` + `sg_migrate` con IP pública, **`--started-by validacion-3-1`** (la rama de prueba de la regla, §5.10), **sin `--group`** (queda `family:campus-locator-dev-validacion`; un `group` `service:…` lo rechaza ECS) y el comando de `app` sobrescrito a `sh -c "echo 'validacion-3-1: sale con error a proposito'; exit 3"`. `ecs wait tasks-stopped` (máx. 10 min) y `ecs describe-tasks` | La tarea queda con `startedBy = validacion-3-1` y `stopCode` ∈ {`EssentialContainerExited`, `TaskFailedToStart`} (lo esperado: `EssentialContainerExited` y `app` con código 3, en ~1 min). Si `run-task` falla, el detalle trae el código y el mensaje de AWS |
| C3b | Sondea cada 30 s (máx. 10 min) `cloudwatch get-metric-statistics` de `AWS/Events` `MatchedEvents`, `Invocations` y `FailedInvocations` (dimensión `RuleName` = la regla, y también `EventBusName` + `RuleName`; se toma la mayor) desde el lanzamiento de C3a; comprueba la suscripción como C1c; sondea (máx. 10 min) `AWS/SNS` `NumberOfMessagesPublished`, `NumberOfNotificationsDelivered` y `NumberOfNotificationsFailed` (`TopicName = campus-locator-dev-alertas`) desde el minuto en que se detuvo la tarea | La regla registra ≥ 1 evento coincidente y ≥ 1 invocación, 0 fallidas, y el topic ≥ 1 notificación entregada y 0 fallidas. Si la suscripción está pendiente, falla enseguida diciendo que la regla sí funcionó |
| C2a | Comprueba la suscripción como C1c (si está pendiente, falla sin enviar nada). Elige una DLQ: la primera de `campus-locator-dev-ingesta-dlq` y `-purga-dlq` sin mensajes (visibles, en vuelo y retrasados en 0) y con su alarma fuera de `ALARM`; si una está vacía pero su alarma sigue en `ALARM`, espera hasta 10 min a que vuelva a `OK`. Envía `{"validacion": "validacion-3-1-<AAAAMMDD-HHMMSS>"}`. Sondea cada 30 s (máx. 20 min) `cloudwatch describe-alarm-history --history-item-type StateUpdate` de su alarma; después, la historia `Action` (máx. 2 min) y las métricas de SNS como C3b desde el minuto del paso a `ALARM`. Al terminar borra su mensaje (salvo con `--sin-limpieza`) | La alarma pasa a `ALARM` después del envío; la historia no muestra una acción fallida (si no muestra ninguna, lo dice el detalle y decide SNS); el topic registra ≥ 1 notificación entregada y 0 fallidas. Si las dos DLQ tienen mensajes ajenos, falla sin enviar nada (sus alarmas ya avisaron; el mensaje de prueba no cambiaría su estado). Si no pasa a `ALARM`, el detalle dice si SQS llegó a publicar la métrica de la cola |

`--solo` admite los alias `C1` (C1a, C1b y C1c), `C2` (C2a) y `C3` (C3a y C3b). Con `--solo C1` no crea nada. C3b
lanza la tarea si C3a no se incluyó (una sola tarea por ejecución). El script se probó contra el AWS falso de
`tests/ops/falsos.py` (ARCHITECTURE §5.11) con métricas que tardan hasta 8 min.

**Cambio de 0.15.0.** En la primera ejecución en `dev` (2026-10-26, sobre `8c98f90`), ECS rechazó el `run-task` con
`--group service:worker` (`InvalidParameterException` «Invalid namespace for group.», CloudTrail): una tarea suelta no
puede llevar un `group` del espacio `service:` (ARCHITECTURE §3.8), así que ninguna casaba con la regla y C3a y C3b
fallaron. Desde 0.15.0 la regla tiene una rama `startedBy = validacion-3-1`, la tarea va sin `group` y C1b prueba la
rama de los servicios con `TestEventPattern`. Con la regla de 0.14.0 todavía aplicada, C1b falla («con "tarea de
prueba de validate31" la regla no avisaría») y C3b también (sin eventos coincidentes): hay que aplicar 0.15.0 antes
(§5, preparación). Desde 0.15.0, cualquier fallo de una llamada a AWS muestra el código y el `Error.Message`
(ARCHITECTURE §5.11, `error_aws`).

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C2b | Revisa el buzón de `correo_alertas` (§5.3) tras C2a; el script imprime (`[MANUAL] C2b …`) el nombre de la alarma y la hora del paso a `ALARM`. El correo es de «AWS Notifications» (`no-reply@sns.amazonaws.com`), con asunto `ALARM: "campus-locator-dev-ingesta-dlq" in US East (N. Virginia)` (o la de `purga-dlq`) | Captura del correo con el nombre de la alarma y la hora, sin la dirección de correo ni el enlace de baja |
| C3c | Revisa el mismo buzón tras C3b; el script imprime el ID de la tarea. El correo («AWS Notification Message») trae el evento `ECS Task State Change` en JSON | Captura del correo donde se vean `startedBy = validacion-3-1` (o el ID de la tarea), `group = family:campus-locator-dev-validacion` y el `stopCode`, sin la dirección de correo ni el enlace de baja |

No llega correo cuando la alarma de la DLQ vuelve a `OK` tras la limpieza (ADR-INF-16). Si un correo no llega en unos
minutos aunque SNS lo dé por entregado, mirar la carpeta de spam (R14).

**Evidencia del cierre** (ejecución del 2026-10-26, 22:47:50–22:54:40 UTC, sobre `91bac0a`, código 0; informe
`.validacion/INF-3.1-20261026-224750.json`):
- C2b: [captura del correo](./evidencia/inf-3-1/c2b-correo-alarma-ingesta-dlq.png) «ALARM: "campus-locator-dev-ingesta-dlq"
  in US East (N. Virginia)» de AWS Notifications, 17:53 de Bogotá, «State Change: OK -> ALARM», «Threshold Crossed: 1
  out of the last 1 datapoints [1.0 (26/10/26 22:51:00)]», 22:53:49 UTC (se ve también el de la primera ejecución,
  17:19). No muestra la dirección de correo.
- C3c: el usuario confirmó por escrito que llegó el correo de la tarea detenida (tarea
  `feb7821458354cffa300ab68366ae1b3`, `startedBy = validacion-3-1`, `EssentialContainerExited`); sin captura.

## 4. Datos de prueba y limpieza

- **C2:** un mensaje en una DLQ con cuerpo `{"validacion": "validacion-3-1-<AAAAMMDD-HHMMSS>"}`. Lo borra el propio C2a
  en cuanto comprueba el aviso (`sqs receive-message` + `delete-message-batch` con `comun.LectorCola`; los ajenos que
  reciba vuelven a la cola con `change-message-visibility-batch --visibility-timeout 0`), y si C2a falla, la limpieza.
  Al borrarlo, la alarma vuelve a `OK` en unos minutos (sin correo). Al empezar, en cada DLQ con entre 1 y 10 mensajes
  visibles y ninguno en vuelo, borra los `validacion-3-1-` de ejecuciones anteriores con más de 1 h (una lectura); los
  de una ejecución más reciente los trata como ajenos. Nunca borra ni cambia mensajes ajenos (solo los recibe una vez y
  los devuelve).
- **C3:** una tarea suelta con `startedBy = validacion-3-1` que se detiene sola en ~1 min. La limpieza (y el comienzo,
  por restos) detiene con `ecs stop-task` cualquier tarea de `ecs list-tasks --cluster campus-locator-dev --started-by
  validacion-3-1 --desired-status RUNNING` que siga viva. La tarea queda en la consola de ECS como detenida (ECS la
  olvida en ~1 h) y escribe una línea en `/campus-locator/dev/validacion` (`validacion/app/<id>`).
- Los correos recibidos no se borran. No toca alarmas, topic, regla ni suscripción.
- La tarea de prueba no lleva `group` de servicio (queda `family:campus-locator-dev-validacion`): no se mezcla con
  las tareas de `api`, `worker` ni `embedding`. Ningún otro validador debe usar `startedBy = validacion-3-1`: la regla
  avisaría de su parada.

## 5. Cómo ejecutarlo

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con lectura del bucket de estado (`terraform output`);
`apigateway:GET`; `application-autoscaling:DescribeScheduledActions`; `cloudwatch:DescribeAlarms`,
`DescribeAlarmHistory` y `GetMetricStatistics`; `events:DescribeRule`, `ListTargetsByRule` y (desde 0.15.0)
`TestEventPattern`; `sns:GetTopicAttributes`,
`ListSubscriptionsByTopic` y `GetSubscriptionAttributes`; `sqs:GetQueueAttributes`, `SendMessage`, `ReceiveMessage`,
`DeleteMessage` y `ChangeMessageVisibility` en las dos DLQ; `ecs:RunTask`, `DescribeTasks`, `ListTasks` y `StopTask`
sobre `campus-locator-dev`; `iam:PassRole` sobre `campus-locator-dev-ecs-ejecucion` y `campus-locator-dev-tarea-migrate`
(la tarea de validación). Para los pasos 3 y 4 de la preparación, sesión de `gh` de la cuenta dueña del repositorio,
revisora del entorno `dev`; para el paso 5, acceso al buzón de `correo_alertas`. La región es `us-east-1` (§5.3). Los
comandos van desde la raíz del repositorio, con `export AWS_REGION=us-east-1`.

**Preparación** (una sola vez, al cerrar el lote; **no el día de campo**: el `apply` lo coordina el maestro).

1. Comprobar que ningún nombre del lote está ocupado (`CreateTopic`, `PutMetricAlarm` y `PutRule` no fallan con un
   nombre que ya existe: lo sobrescriben, y Terraform se quedaría con un recurso ajeno) y que las DLQ están vacías:
   ```bash
   aws cloudwatch describe-alarms --alarm-names campus-locator-dev-api-5xx campus-locator-dev-ingesta-dlq \
     campus-locator-dev-purga-dlq campus-locator-dev-embedding-encendida campus-locator-dev-rds-almacenamiento \
     campus-locator-dev-rds-creditos-cpu --query 'MetricAlarms[].AlarmName' --output text
   aws sns list-topics --query "Topics[?ends_with(TopicArn, ':campus-locator-dev-alertas')].TopicArn" --output text
   aws events list-rules --name-prefix campus-locator-dev-tarea-detenida --query 'Rules[].Name' --output text
   for q in campus-locator-dev-ingesta-dlq campus-locator-dev-purga-dlq; do
     aws sqs get-queue-attributes --queue-url "$(aws sqs get-queue-url --queue-name $q --query QueueUrl --output text)" \
       --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text
   done
   ```
   Esperado: los tres primeros no imprimen nada; el bucle, `0` y `0` (así lo estaban el 2026-10-26). Si aparece un
   nombre, parar y revisarlo. Si una DLQ tiene mensajes, su alarma avisará en cuanto se cree y se confirme la
   suscripción (es un aviso real: revisarla).
2. Comprobaciones locales, pruebas y `plan` (este lote no añade proveedores: el lock no cambia):
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform fmt -check -recursive && echo FMT_OK
   terraform -chdir=envs/dev init -input=false -lockfile=readonly >/dev/null
   terraform -chdir=envs/dev validate
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -no-color \
     | grep -E '^Plan:|will be (updated|destroyed|replaced)|^  \+ sns_alertas_arn'
   git diff --exit-code envs/dev/.terraform.lock.hcl && echo LOCK_SIN_CAMBIOS
   uv run --group ops --group pruebas pytest tests/ops -q
   cd ../..
   ```
   Esperado: `FMT_OK`, `Success! The configuration is valid.`, `Plan: 11 to add, 0 to change, 0 to destroy.` (todo en
   `module.observabilidad`), `+ sns_alertas_arn = (known after apply)`, `LOCK_SIN_CAMBIOS` y `45 passed` (37 en
   0.14.0, cuando se aplicó; ya aplicado 0.14.0, este `plan` dio `No changes` el 2026-10-26; para 0.15.0, ver
   «Cambio de 0.15.0» más abajo); ninguna línea
   `will be updated`, `destroyed` ni `replaced` (en particular, nada de `computo`, `borde` ni `datos`, que solo ganan
   outputs). Un *push* directo a `main` no tiene `plan` en un PR (§3.9): este es el que revisa quien aprueba el paso 4.
3. Commit y *push* a `main` de los módulos, `envs/dev`, los validadores, las pruebas y `docs/`:
   ```bash
   git add INFRASTRUCTURA_TERRAFORM/project/modules/observabilidad INFRASTRUCTURA_TERRAFORM/project/modules/borde \
     INFRASTRUCTURA_TERRAFORM/project/modules/computo INFRASTRUCTURA_TERRAFORM/project/modules/datos \
     INFRASTRUCTURA_TERRAFORM/project/envs/dev INFRASTRUCTURA_TERRAFORM/project/src/ops \
     INFRASTRUCTURA_TERRAFORM/project/tests INFRASTRUCTURA_TERRAFORM/project/pyproject.toml \
     INFRASTRUCTURA_TERRAFORM/project/uv.lock INFRASTRUCTURA_TERRAFORM/docs
   git status --short
   git commit -m "INF-3.1: observabilidad y alarmas"
   git push origin main
   ```
   Esperado: `git status --short` no muestra nada bajo `.terraform/`, `.validacion/`, `.venv/` ni `__pycache__/`, ni
   nada de esta carpeta sin añadir. En GitHub arranca `infra.yml` y su job `apply (main)` queda esperando la aprobación
   del entorno `dev` (si hay otra ejecución de `main` de un commit anterior esperando, retiene la fila: cancelarla).
4. Aprobar el `apply`: igual que el paso 4 de [`validation-1-1`](./validation-1-1.md) §5, con `comment="INF-3.1"`.
   Esperado: `gh run watch` termina con 0 y el log dice `Apply complete! Resources: 11 added, 0 changed, 0 destroyed.`
5. Confirmar la suscripción: en el buzón de `correo_alertas` llega «AWS Notification - Subscription Confirmation»
   (de `no-reply@sns.amazonaws.com`; mirar spam); abrir su enlace *Confirm subscription*. Comprobar:
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   aws sns list-subscriptions-by-topic --topic-arn "$(terraform -chdir=envs/dev output -raw sns_alertas_arn)" \
     --query 'Subscriptions[].[Protocol,SubscriptionArn]' --output text
   cd ../..
   ```
   Esperado: una línea `email	arn:aws:sns:us-east-1:648617469176:campus-locator-dev-alertas:<id>`. Con
   `PendingConfirmation`, todavía no se confirmó. El enlace vale 2 días (documentación de `sns:Subscribe`); si caduca,
   se pide otro desde la consola de SNS (la suscripción → *Request confirmation*; sin comprobar).
6. Comprobar que no quedan diferencias y ver el estado de las alarmas:
   ```bash
   cd INFRASTRUCTURA_TERRAFORM/project
   terraform -chdir=envs/dev plan -input=false -lock-timeout=60s -detailed-exitcode -no-color | grep -E '^(No changes|Plan:)'
   echo "codigo=${PIPESTATUS[0]}"
   aws cloudwatch describe-alarms --alarm-name-prefix campus-locator-dev- \
     --query 'MetricAlarms[].[AlarmName,StateValue,length(AlarmActions)]' --output text
   cd ../..
   ```
   Esperado: `No changes. Your infrastructure matches the configuration.` y `codigo=0`; 10 alarmas: las 4 de INF-2.1
   (cualquier estado; `worker-colas-vacias` y `embedding-inactivo` suelen estar en `ALARM` sin uso) y las 6 de INF-3.1
   en `OK` (o `INSUFFICIENT_DATA` los primeros minutos), todas con 1 acción. Si una de INF-3.1 está en `ALARM`, es un
   aviso real (o la de `embedding-encendida`, si `embedding` lleva ~10 h encendido).

Este lote no cambia las variables del repositorio de GitHub (§5.9).

**Cambio de 0.15.0 sobre lo ya aplicado** (la regla con la rama `startedBy`). Los pasos 1 y 5 no hacen falta (nada nuevo
que crear ni que confirmar). Paso 2: `Plan: 0 to add, 1 to change, 0 to destroy.`, con una sola línea `will be updated
in-place`, la de `module.observabilidad.aws_cloudwatch_event_rule.tarea_detenida`, y en su diff solo el
`event_pattern` (`+ "$or" = [{ group = […] }, { startedBy = ["validacion-3-1"] }]` y `- group = […]` dentro de
`detail`); `45 passed`. Pasos 3 y 4 igual, con el mensaje y el comentario del cambio; el log dice `Apply complete!
Resources: 0 added, 1 changed, 0 destroyed.` Paso 6 igual (`No changes`).

**Ejecución** (~10–30 min; sin hora límite; no el día de campo). Mientras corre, nadie debe re-enviar mensajes de las
DLQ (*redrive*):

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate31.py --entorno dev
```

Esperado (los tiempos varían):

```
[PASA] P4 arn:aws:iam::648617469176:… (cuenta 648617469176)
[PASA] P1 campus-locator-dev-api (fuzq99kddb)
[PASA] P2 campus-locator-dev-embedding-apagar-noche
[PASA] P3 sns_alertas_arn, api_base_url, ecs_cluster, familias_tarea, subredes_tareas, sg_migrate, sqs_ingesta_dlq_url, sqs_purga_dlq_url
[PASA] C1a las 6 alarmas de §5.10 avisan a campus-locator-dev-alertas con sus umbrales; estados: api-5xx OK, …
[PASA] C1b campus-locator-dev-tarea-detenida ENABLED con el patrón de §5.10 (service:api, service:embedding, service:worker o startedBy validacion-3-1; EssentialContainerExited, TaskFailedToStart) → campus-locator-dev-alertas; TestEventPattern: 9 casos como se espera; la política del topic deja publicar a la regla y a CloudWatch
[PASA] C1c suscripción email a fr…@gmail.com confirmada
[PASA] C3a tarea <id> (group family:campus-locator-dev-validacion, startedBy validacion-3-1) detenida con stopCode EssentialContainerExited (app salió con 3) a los 0.9 min (…)
[PASA] C3b campus-locator-dev-tarea-detenida: 1 evento(s) coincidente(s), 1 invocación(es), 0 fallidas; SNS: 1 entregada(s), 0 fallidas
[PASA] C2a campus-locator-dev-ingesta-dlq → ALARM a los 3.0 min del envío (…); SNS: 1 entregada(s), 0 fallidas
[MANUAL] C2b revisar el buzón de fr…@gmail.com: el correo de CloudWatch «ALARM: "campus-locator-dev-ingesta-dlq" …» de las HH:MM de Bogotá; …
[MANUAL] C3c revisar el buzón de fr…@gmail.com: el correo «AWS Notification Message» con el evento ECS Task State Change de la tarea <id> (…); …
Resultado: pasa (código 0) · informe: …/project/.validacion/INF-3.1-<AAAAMMDD-HHMMSS>.json
```

En stderr, entre otros, `mensaje validacion-3-1 borrado de campus-locator-dev-ingesta-dlq (su alarma vuelve a OK en unos
minutos)` y `limpieza hecha: …`. Con la suscripción sin confirmar: `[FALLA]` en C1c, C3b y C2a con «pendiente de
confirmación» y código 1 (C2a no envía nada). Si se interrumpe con Ctrl+C, la limpieza borra el mensaje y detiene la
tarea igual.

Con la regla de 0.14.0 todavía aplicada (sin el `apply` de 0.15.0): `[FALLA] C1b … con «tarea de prueba de validate31»
la regla no avisaría`, `[FALLA] C3b … no registró ningún evento coincidente …` y código 1. En la ejecución del
2026-10-26 con el validador de 0.14.0, C3a falló con `InvalidParameterException` (el `group`) y C2a dio
`campus-locator-dev-ingesta-dlq → ALARM a los 2.7 min del envío (17:19 de Bogotá); SNS: 1 entregada(s), 0 fallidas`.
