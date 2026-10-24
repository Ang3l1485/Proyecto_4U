# Validación 2-1 — INF-2.1 Escalado del `worker` y horario de `dev`

| Campo | Valor |
|---|---|
| Lote | `INF-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.3 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `dev` |
| Criterios | Automáticos: C1, C2, C3 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado` (P3 y P4 son de credenciales y de
uso: código 3, según §5.11).

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.3` en «Hecho»: servicios `worker` y `embedding` creados | `ecs describe-services --cluster campus-locator-dev --services worker embedding` devuelve los dos con `status = ACTIVE` |
| P2 | Outputs del clúster y de las colas | `terraform -chdir=envs/dev output -json` contiene `ecs_cluster`, `ecs_servicios`, `sqs_ingesta_url` y `sqs_purga_url` |
| P3 | Credenciales de la cuenta `648617469176` | `aws sts get-caller-identity` devuelve `Account = 648617469176` |
| P4 | La ejecución empieza dentro del horario con margen (C2 y C3 necesitan ~50 min con `worker` habilitado) | La hora actual en `America/Bogota` (`zoneinfo`) está entre 06:00 y 21:00 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids service/campus-locator-dev/embedding service/campus-locator-dev/worker` y `describe-scheduled-actions` de cada uno; calcula la próxima ejecución de cada acción | Dos destinos con `ScalableDimension = ecs:service:DesiredCount`; cada servicio tiene dos acciones con `Timezone = America/Bogota`: `cron(0 6 * * ? *)` (`embedding` Min = Max = 1; `worker` Min = 0, Max = 1) y `cron(0 22 * * ? *)` (`embedding` Min = Max = 0; `worker` Max = 0). El detalle incluye la próxima ejecución |
| C1b | `application-autoscaling describe-scaling-activities --service-namespace ecs --resource-id service/campus-locator-dev/embedding` y `ecs describe-services --services embedding` | La última ejecución de cada acción (22:00 y 06:00 hora de Bogotá, ±10 min) aparece como actividad `Successful` cuya `Cause` cita la acción programada, y deja la capacidad deseada en 0 y en 1; ahora `desiredCount = 1`. Si desde el `apply` aún no han pasado las dos horas, falla con ese detalle y se repite al día siguiente |
| C2a | `application-autoscaling describe-scaling-policies --resource-id service/campus-locator-dev/worker` y `cloudwatch describe-alarms` de sus `Alarms` | Políticas `StepScaling` cuyas alarmas usan `ApproximateNumberOfMessagesVisible` ≥ 1 de `campus-locator-dev-ingesta` y de `campus-locator-dev-purga` para subir a 1, y una que baja a 0 tras 15 min sin mensajes visibles ni en vuelo |
| C2b | Con `worker` en `desiredCount = 0`, envía con `sqs send-message` 3 mensajes a `ingesta` con la forma de `s3:TestEvent` (el `worker` los borra sin hacer nada, `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.8) y `RequestId = validacion-2-1-<AAAAMMDD-HHMMSS>-<n>`; sondea `ecs describe-services --services worker` cada 30 s (máx. 20 min). Luego consume y borra sus mensajes, anota cuándo `ApproximateNumberOfMessages` y `ApproximateNumberOfMessagesNotVisible` de `ingesta` y `purga` llegan a 0 y sigue sondeando (máx. 35 min) | `desiredCount` pasa a 1 y vuelve a 0 entre 12 y 30 min después de vaciarse las colas. Se mira `desiredCount`, no `runningCount`: con la imagen `bootstrap` la tarea de `worker` puede detenerse al arrancar. Si hay mensajes ajenos en las colas, falla con ese detalle |
| C3 | Emula el estado de las 22:00 sin esperar a la noche: guarda `MinCapacity` y `MaxCapacity` de `worker` y aplica `application-autoscaling register-scalable-target --max-capacity 0` (lo mismo que la acción de las 22:00 de C1a). Envía 3 mensajes como en C2b, espera a que la alarma de subida esté en `ALARM` (máx. 15 min) y observa 5 min más; después borra sus mensajes y restaura la capacidad guardada | `desiredCount` de `worker` sigue en 0 todo el intervalo y `describe-scaling-activities` no registra ninguna subida en él |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea mensajes en `ingesta` con la forma de `s3:TestEvent` y `RequestId` que empieza por `validacion-2-1-`. Los consume
y borra (`sqs receive-message` + `delete-message`) al terminar cada comprobación; los ajenos vuelven a la cola sin
tocarse (`change-message-visibility --visibility-timeout 0`). Si el `worker` real los recibe antes, los borra él. En la
limpieza, siempre: borra los mensajes `validacion-2-1-` que queden y restaura `MinCapacity`/`MaxCapacity` de `worker`
a lo guardado. Nunca cambia `desiredCount` a mano. Al empezar borra mensajes `validacion-2-1-` de ejecuciones
anteriores y, si `worker` tiene `MaxCapacity = 0` dentro del horario (una ejecución interrumpida en C3), lo devuelve a
`MinCapacity = 0`, `MaxCapacity = 1`, los valores de la acción de las 06:00. Si INF-3.1 ya está aplicado y `worker`
usa la imagen `bootstrap`, las paradas de C2b pueden enviar avisos de la regla de EventBridge.

## 5. Cómo ejecutarlo

```bash
cd INFRASTRUCTURA_TERRAFORM/project
uv run --group ops python src/ops/validate21.py --entorno dev
```

Variables: `AWS_PROFILE` con el perfil de la persona (§5.11), con permiso para `sqs:SendMessage` en `ingesta` y
`application-autoscaling:RegisterScalableTarget`. La región es `us-east-1` (§5.3). Debe empezar entre 06:00 y 21:00
hora de Bogotá (P4). Duración aproximada: 45–60 min (las métricas de una cola inactiva pueden tardar hasta 15 min).
