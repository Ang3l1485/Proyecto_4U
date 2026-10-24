# Validación 3-1 — INF-3.1 Observabilidad y alarmas

| Campo | Valor |
|---|---|
| Lote | `INF-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate31.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2a, C3a, C3b · Manuales: C2b, C3c |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P4 es de credenciales: código 3,
según §5.11).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.4` en «Hecho»: HTTP API creada (su `ApiId` es la dimensión de la alarma de 5xx) | `apigatewayv2 get-apis` contiene `campus-locator-dev-api` y su `ApiEndpoint` = output `api_base_url` |
| P2 | `INF-2.1` en «Hecho»: horario aplicado | `application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id service/campus-locator-dev/embedding` devuelve las dos acciones |
| P3 | Outputs que usa el script | `terraform -chdir=envs/dev output -json` contiene `sns_alertas_arn`, `ecs_cluster`, `familias_tarea`, `subredes_tareas`, `sg_migrate`, `sqs_ingesta_dlq_url` y `sqs_purga_dlq_url` |
| P4 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `cloudwatch describe-alarms --alarm-names` con los seis nombres de alarma de §5.1 | Existen las seis y cada una corresponde a su umbral de §5.10, con `AlarmActions` que incluye `sns_alertas_arn`: `AWS/ApiGateway` `5xx` (`ApiId` de P1) `Sum` > 5 en 300 s; `AWS/SQS` `ApproximateNumberOfMessagesVisible` ≥ 1 en `campus-locator-dev-ingesta-dlq` y otra en `campus-locator-dev-purga-dlq`; `AWS/ECS` `CPUUtilization` de `ClusterName = campus-locator-dev`, `ServiceName = embedding` > 90 durante 900 s; `AWS/RDS` de `campus-locator-dev-db`: `FreeStorageSpace` < 4 294 967 296 bytes (4 GiB) y `CPUCreditBalance` < 20 |
| C1b | `events describe-rule --name campus-locator-dev-tarea-detenida`, `events list-targets-by-rule` y `sns get-topic-attributes` | La regla está `ENABLED` con `source = aws.ecs`, `detail-type = ECS Task State Change`, el clúster `campus-locator-dev`, `lastStatus = STOPPED`, `stopCode` ∈ {`EssentialContainerExited`, `TaskFailedToStart`} y `group` ∈ {`service:api`, `service:worker`, `service:embedding`} (ARCHITECTURE §3.8); su destino es `sns_alertas_arn` y la `Policy` del topic permite `sns:Publish` a `events.amazonaws.com` |
| C1c | `sns list-subscriptions-by-topic --topic-arn <sns_alertas_arn>`; lee `correo_alertas` de `envs/dev/terraform.tfvars` | Hay una suscripción `email` a `correo_alertas` y su `SubscriptionArn` no es `PendingConfirmation` |
| C2a | `sns list-subscriptions-by-topic`. Envía a `campus-locator-dev-ingesta-dlq` un mensaje con cuerpo `{"validacion": "validacion-3-1-<AAAAMMDD-HHMMSS>"}` (si esa DLQ ya tiene mensajes ajenos usa `purga-dlq`; si ambas los tienen, falla). Sondea `cloudwatch describe-alarm-history --history-item-type StateUpdate` de su alarma (máx. 20 min) y luego `cloudwatch get-metric-statistics` de `AWS/SNS` `NumberOfNotificationsDelivered` y `NumberOfNotificationsFailed` (`TopicName = campus-locator-dev-alertas`) | Hay una suscripción `email` confirmada (no `PendingConfirmation`); la alarma pasa a `ALARM` después del envío; el topic registra ≥ 1 notificación entregada y 0 fallidas en ese intervalo |
| C3a | `ecs run-task` de la familia `campus-locator-dev-api` con `--group service:api` y `--started-by validacion-3-1` (la regla solo avisa por tareas de servicio, ARCHITECTURE §3.8; con ese `group` la tarea cuenta como de `api`), red `subredes_tareas` + `sg_migrate`, y el comando de `app` sobrescrito a un ejecutable inexistente (`/validacion-inexistente`); `ecs wait tasks-stopped` y `ecs describe-tasks` | La tarea termina con `stopCode` = `TaskFailedToStart` o `EssentialContainerExited` |
| C3b | `cloudwatch get-metric-statistics` de `AWS/Events` `MatchedEvents`, `Invocations` y `FailedInvocations` (`RuleName` = la regla de C1b) y de `AWS/SNS` `NumberOfNotificationsDelivered`, desde el lanzamiento de C3a hasta 10 min después | La regla registra ≥ 1 evento coincidente y ≥ 1 invocación, 0 fallidas, y el topic ≥ 1 notificación entregada |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C2b | Revisa el buzón de `correo_alertas` (§5.3) tras C2a; el script imprime el nombre de la alarma y la hora del cambio de estado | Captura del correo de CloudWatch con el nombre de la alarma de la DLQ y la hora |
| C3c | Revisa el mismo buzón tras C3a; el script imprime el ID de la tarea | Captura del correo con el evento `ECS Task State Change` de esa tarea (ID o `startedBy = validacion-3-1`) y su `stopCode` |

## 4. Datos de prueba y limpieza

Crea un mensaje en una DLQ con la marca `validacion-3-1-<AAAAMMDD-HHMMSS>` y una tarea suelta con
`startedBy = validacion-3-1` que se detiene sola. Limpieza, siempre: consume y borra de la DLQ solo el mensaje con su
marca (`sqs receive-message` + `delete-message`; los ajenos vuelven con `change-message-visibility
--visibility-timeout 0`), con lo que la alarma vuelve a `OK` en unos minutos; detiene con `ecs stop-task` cualquier
tarea de `ecs list-tasks --cluster campus-locator-dev --started-by validacion-3-1` que siga viva. Al empezar hace lo
mismo con restos de ejecuciones anteriores (mensajes con marca `validacion-3-1-` en las dos DLQ). Los correos
recibidos no se borran.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate31.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con permiso para `sqs:SendMessage` en las DLQ,
`ecs:RunTask` e `iam:PassRole`; acceso al buzón de `correo_alertas` para C2b y C3c. La región es `us-east-1` (§5.3).
Duración aproximada: 15–30 min (la alarma de una DLQ inactiva puede tardar hasta 15 min).
