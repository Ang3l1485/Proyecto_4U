# CHANGELOG — Infraestructura (`INFRASTRUCTURA_TERRAFORM`)

Una entrada por versión de [`ARCHITECTURE.md`](./ARCHITECTURE.md), la más reciente primero.

**Cómo se numera la versión del documento**
- **Mayor** (`1.0.0` → `2.0.0`): cambia un contrato de §5 de forma incompatible (renombrar un output, una variable de
  entorno, una cola…). Mientras la versión sea `0.x`, un cambio incompatible sube la **menor**.
- **Menor** (`0.1.0` → `0.2.0`): contrato nuevo o ampliación compatible, o una decisión nueva (ADR).
- **Parche** (`0.1.0` → `0.1.1`): aclaraciones o correcciones de redacción sin efecto en contratos.

**Plantilla de entrada**
```
## [x.y.z] — AAAA-MM-DD
- Lote que la motivó:
- Qué cambió:
- Contratos tocados (§5):
- Cómo se verificó:
- Pendiente:
```

---

## [0.15.1] — 2026-10-26

- **Lote que la motivó:** INF-3.1, cierre en `dev`.
- **Qué cambió:** solo documentos. INF-3.1 pasa a «Hecho» en PLAN §3 (`91bac0a`, 2026-10-26). Encabezado, §3.8, §5.11,
  §5.12 y R13 dicen lo comprobado y quitan los «sin comprobar» que ya no lo son: la parada de la tarea de prueba, que
  EventBridge publica con la condición `aws:SourceArn` de la política, el `apply` de 0.15.0 y la forma del correo de
  CloudWatch. `validation-3-1` §3 enlaza la evidencia de C2b (`evidencia/inf-3-1/c2b-correo-alarma-ingesta-dlq.png`)
  y anota la confirmación escrita de C3c.
- **Contratos tocados (§5):** ninguno. Sube el parche.
- **Cómo se verificó:** `91bac0a` aplicado por `infra.yml` (ejecución 40414967226: `Plan: 0 to add, 1 to change, 0 to
  destroy.` y `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`), aprobado por el maestro con la
  autorización del usuario. `validate31.py --entorno dev` sobre `91bac0a` con código 0 (2026-10-26 22:47:50–22:54:40
  UTC; informe `.validacion/INF-3.1-20261026-224750.json`): pasan P1–P4; C1a (6 alarmas en `OK`); C1b (patrón con
  `startedBy validacion-3-1`, `TestEventPattern` con los 9 casos como se espera, política); C1c; C3a (tarea
  `feb7821458354cffa300ab68366ae1b3`, `family:campus-locator-dev-validacion`, `EssentialContainerExited`, código 3, a
  los 1,3 min); C3b (1 evento coincidente, 1 invocación, 0 fallidas; SNS 1 entregada, 0 fallidas); C2a (`ingesta-dlq`
  → `ALARM` a los 2,7 min; SNS 1 entregada); limpieza hecha. Manuales: C2b con captura del correo (sin la dirección);
  C3c, confirmación escrita del usuario. La primera ejecución (22:16 UTC, sobre `8c98f90`) dio código 1 en C3 por el
  `group` (0.15.0).
- **Pendiente:** ninguno del lote (INF-3.1 «Hecho»). Sin comprobar todavía (§3.8): el `stopCode` de una tarea
  reemplazada por *health checks*, eventos repetidos, la métrica de una DLQ inactiva con mensajes, el texto de una acción
  fallida de una alarma y que la alarma de `embedding` encendido dispare tras 10 h. Lo de 0.12.0: §5.13 con la imagen de
  BE-1.1 y la propuesta de R10.

---

## [0.15.0] — 2026-10-26

- **Lote que la motivó:** INF-3.1, tras su primera validación en `dev` (C3 no podía pasar).
- **Qué cambió:**
  - **Regla `campus-locator-dev-tarea-detenida`** (§3.8, §5.10): en `detail`, `group` pasa a ser una rama de `"$or"`
    con una segunda rama, `startedBy = validacion-3-1` (`local.marca_prueba` del módulo), que solo lleva la tarea de
    prueba de `validate31.py`. Motivo: ECS rechaza una tarea suelta con `group = service:worker`
    (`InvalidParameterException` «Invalid namespace for group.»), así que ninguna tarea suelta podía casar con la regla
    y C3 no podía pasar sin detener un servicio. Decisión del maestro (opción A de las tres que se estudiaron; ADR-INF-16,
    corrección en 0.15.0): conserva el C3 de PLAN («llega el correo») y no avisa de más (`migrate` y las demás tareas
    sueltas siguen sin avisar aunque salgan con 0).
  - La política del topic nombra la regla con su ARN escrito (`arn:aws:events:<region>:<cuenta>:rule/<prefijo>-tarea-
    detenida`) en vez de `aws_cloudwatch_event_rule.tarea_detenida.arn`: con la referencia, el primer `plan` de este
    cambio daba `0 to add, 2 to change` (la política *known after apply*, aunque quedaba igual). Ahora: `0 to add,
    1 to change, 0 to destroy`, solo el `event_pattern` (§5.12).
  - `validate31.py`: la tarea de prueba se lanza sin `--group` (queda `family:campus-locator-dev-validacion`) y con
    `startedBy = validacion-3-1`; C3a exige ese `startedBy` (antes, `group = service:worker`). C1b compara el patrón
    con el nuevo y además lo prueba con `events:TestEventPattern` contra 9 eventos sintéticos (`CASOS_PATRON`, §5.12):
    la rama de los servicios, que C3 no ejercita, y lo que no debe avisar (`migrate` que sale con 0, la tarea de
    validación de otro validador, `ServiceSchedulerInitiated`, otro clúster, `lastStatus` distinto de `STOPPED`).
    Permiso nuevo para quien lo ejecuta: `events:TestEventPattern` (`validation-3-1` §5).
  - `comun.error_aws` (y con ella `errores_aws` y todos los validadores de esta carpeta) añade al código de error de
    AWS su `Error.Message`, en una línea y recortado, sin IDs de llaves de acceso ni firmas o credenciales de URL
    prefirmadas (función interna `_mensaje_error_aws`). Antes, un fallo de API solo decía el código (p. ej.
    `lanzar la tarea de prueba (ecs:RunTask): InvalidParameterException`, sin el motivo). §5.11, tabla de `comun.py`.
  - `tests/ops/falsos.py`: `error(codigo, operacion, mensaje=None)`; `coincide` entiende `$or`; `test_event_pattern`;
    `run_task` rechaza, como ECS, un `group` que empiece por `service:` y sin `group` deja `family:<definición>`;
    `patron_bien()` es el patrón nuevo y `patron_0_14()` el viejo; el interruptor `run_task_falla` reemplaza a
    `ecs_acepta_group` y `ecs_respeta_group`. Pruebas: 5 de `error_aws` en `test_comun.py`; en `test_validate31.py`,
    el patrón viejo (C1b y C3b fallan), uno demasiado amplio (C1b: «migrate … avisaría»), un `run-task` que falla, el
    falso que rechaza `service:` y la concordancia de `CASOS_PATRON` con `patron_esperado()` y `patron_bien()`
    (45 en total).
  - Lo comprobado en `dev` (§3.8, encabezado y PLAN): el `apply` de 0.14.0 (ejecución 40377985054 de `infra.yml`,
    11 recursos), la suscripción confirmada, el `plan` vacío después y `validate31.py` sobre `8c98f90`: pasan P1–P4,
    C1a, C1b, C1c y C2a (`ingesta-dlq` → `ALARM` a los 2,7 min, 1 notificación entregada; la historia de la alarma trae
    la entrada `Action`); fallan C3a y C3b por el `group`.
  - Corrige una contradicción: §3.8, §5.11, ADR-INF-16 y `validation-3-1` daban por posible lanzar una tarea suelta
    con `group = service:worker`; ECS lo rechaza (CloudTrail, `RunTask` del 2026-10-26 a las 22:17:05 UTC). Ahora lo
    dicen, con la trampa en §3.8.
- **Contratos tocados (§5):** §5.10 (patrón de la regla, ampliado de forma compatible: avisa de lo mismo y además de la
  tarea de prueba), §5.11 (texto de `error_aws`; tarea de validación sin `group`) y §5.12 (módulo `observabilidad`).
  Sube la menor.
- **Cómo se verificó:**
  - `terraform fmt -check -recursive` y `validate`; `plan -lock=false` contra `dev` sobre `8c98f90`: `Plan: 0 to add,
    1 to change, 0 to destroy.`, solo `module.observabilidad.aws_cloudwatch_event_rule.tarea_detenida`, atributo
    `event_pattern` (en `detail`: `+ "$or" = [{group = […]}, {startedBy = ["validacion-3-1"]}]` y `- group = […]`; lo
    demás igual); lock sin cambios.
  - `uv run --group ops --group pruebas pytest tests/ops -q`: 45 pasan; `uvx ruff@0.14.0 check --line-length 120
    src/ops tests/ops` sin avisos.
  - El mensaje de ECS, con `aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=RunTask`
    (solo lectura; `requestParameters`: `group = service:worker`, `startedBy = validacion-3-1`, `taskDefinition =
    campus-locator-dev-validacion`). La documentación de ECS (*Group related Amazon ECS tasks*) solo dice que el grupo
    de una tarea de servicio es el nombre del servicio y no se puede cambiar; no menciona el rechazo. `$or` dentro de
    `detail`: documentación de EventBridge (*Comparison operators*, «Or (multiple fields)»).
  - Tras el `apply` de 0.14.0 y la confirmación, `plan -lock=false -detailed-exitcode` sobre `8c98f90` daba
    `No changes` y código 0, y `list-subscriptions-by-topic` mostraba la suscripción `email` con su ARN.
  - En `dev`: pendiente (`apply` de este cambio y `validate31.py`).
- **Pendiente:** el `apply` por `infra.yml` (`Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`), antes del
  2026-10-27 (día de campo) o después; `validate31.py` en `dev` y las capturas de C2b y C3c. Sin comprobar hasta
  entonces: que EventBridge publique con la condición `aws:SourceArn` de la política y que `TestEventPattern` dé lo
  mismo que el falso con los 9 casos. Opciones descartadas para C3: un `group` propio sin espacio de nombres
  (`validacion-3-1`; que ECS lo acepte estaba sin comprobar) y probar solo el patrón con `TestEventPattern` (no cumple
  «llega el correo» de PLAN C3 y deja sin probar la entrega al topic); también, un servicio de ECS temporal que falle.
  Lo de 0.12.0: §5.13 con la imagen de BE-1.1 y la propuesta de R10.

---

## [0.14.0] — 2026-10-26

- **Lote que la motivó:** INF-3.1 (observabilidad y alarmas).
- **Qué cambió:**
  - Código: módulo `observabilidad` con 11 recursos (topic `campus-locator-dev-alertas` sin cifrar, su política y la
    suscripción por correo; las 6 alarmas de §5.10 con acción solo en `ALARM`; la regla
    `campus-locator-dev-tarea-detenida` y su destino); outputs nuevos de módulo `borde.api_id`, `computo.cluster_arn` y
    `datos.rds_identificador` (sin cambiar recursos); en `envs/dev`, la variable `correo_alertas`, la llamada a
    `module.observabilidad` con sus entradas y el output `sns_alertas_arn`. `src/ops/validate31.py`, y las primeras
    pruebas versionadas de un validador de esta carpeta: `tests/ops/` (`falsos.py`, un AWS falso con reloj;
    `test_validate31.py`; `test_comun.py`) con el grupo `pruebas` (pytest) en `pyproject.toml` y `uv.lock`.
  - `LectorCola` pasa de `validate21.py` a `comun.py` con un clasificador como parámetro, como pedía §5.12 («si otro
    validador las necesita, se mueven allí»): `validate21.py` la usa con su `clasificar` y la misma visibilidad (120 s);
    su comportamiento no cambia.
  - Nueva ADR-INF-16: un topic con suscripción por correo; avisar solo al pasar a `ALARM`; la regla manda el evento
    tal cual; topic sin cifrar (con `aws/sns` CloudWatch y EventBridge no pueden publicar); y C3 se valida con la tarea
    de validación lanzada con `group = service:worker`, sin detener ningún servicio.
  - §3.8: cómo avisan (un correo por paso a `ALARM`, `notBreaching`), qué trae cada correo, política del topic y
    trampas (los 500 de API Gateway con `api` en 0 y los 503 de `/v1/localize` con `embedding` apagado cuentan como
    5xx; la alarma de `embedding` mira horas de reloj; la baja desde el enlace de un aviso) y lo que queda sin comprobar
    (*health checks*, eventos repetidos, DLQ inactiva; y hasta `validate31.py` en `dev`: el `group` en `run-task`, la
    condición `aws:SourceArn` para EventBridge y el texto de la historia `Action`).
    §3.10: fila propia de INF-3.1 (0,6 USD/mes) y CloudWatch en 3,2; el total no cambia. §4: árbol (módulo y
    `tests/ops/`) y fila de INF-3.1. R13 y nuevo R14 (los avisos no llegan).
  - §5.1: suscripción y destino `sns-alertas`. §5.2: valor de `sns_alertas_arn` y quién lo usa. §5.3: `correo_alertas`
    en `envs/dev`. §5.6: política del topic. §5.10: tabla exacta de las 6 alarmas, patrón de la regla, valores medidos
    antes del `apply` y qué editar a la vez al cambiar una alarma, el patrón o la política (Terraform, `validate31.py` y
    `tests/ops/falsos.py`). §5.11: `comun.LectorCola`, lo que se usa de `embedding.py` (`llamar`, `hora_bogota`,
    constantes), el comando de la tarea de prueba de C3, las pruebas locales con `falsos.py` (elementos, constantes,
    límites, ayudas de `test_validate31.py` y la trampa de `import falsos`) y el lint con `ruff --line-length 120`.
    §5.12: entradas, salidas, recursos y detalles del módulo `observabilidad` (forma de `local.alarmas` y la trampa de
    los nombres ocupados, que `CreateTopic`, `PutMetricAlarm` y `PutRule` sobrescriben), las salidas nuevas de `borde`,
    `computo` y `datos`, y las ayudas propias de `validate31.py` (con sus tiempos y la trampa del formato de
    `correo_alertas` en `terraform.tfvars`).
  - `validation-3-1.md` reescrito con el script: C1 en C1a (alarmas), C1b (regla y política) y C1c (suscripción); C3a
    y C3b antes que C2a (C3 tarda ~5 min; C2, hasta 30); §5 con Variables, Preparación y Ejecución. PLAN: entregables de
    INF-3.1 y su fila de §3 en «En curso».
  - Corrige contradicciones: (1) §5.6 decía que AWS Budgets publica en el topic; Budgets escribe directamente al correo
    (§3.8 y `bootstrap/presupuesto.tf`). (2) §3.10 contaba las 6 alarmas de INF-3.1 dentro de «CloudWatch … 10 alarmas»
    sin decirlo; ahora tienen su fila. (3) El comentario de `modules/observabilidad/main.tf` preveía *log groups* en el
    módulo; los crean `computo` y `borde` (§3.8). (4) `validation-3-1` C3a lanzaba la definición de `api` con
    `group = service:api` y un ejecutable inexistente: el `ENTRYPOINT` de la imagen real del backend no es de esta
    carpeta (el comando podría no ejecutarse como se espera), la tarea leería los secretos de `api` y una tarea falsa en
    el grupo de `api` podría confundirse con la real; ahora usa la tarea de validación (`postgres:17-alpine`, comando
    `sh -c '… exit 3'`, como `validate13.py`) con `group = service:worker`.
- **Contratos tocados (§5):** §5.1, §5.2, §5.3 (variable nueva en `envs/dev`), §5.6, §5.10, §5.11 (`comun.py`) y §5.12
  (módulos). Compatible: sube la menor.
- **Cómo se verificó:** en local, con Terraform 1.16.6 en WSL sobre `e037904` (rama `fuera/inf-3-1`): `terraform fmt
  -check -recursive` y `validate` de `envs/dev` sin errores; `plan -lock=false` contra `dev`: `Plan: 11 to add, 0 to
  change, 0 to destroy.`, las 11 altas en `module.observabilidad`, 102 recursos sin cambios (los 12 de INF-2.1
  incluidos), `+ sns_alertas_arn` y el lock sin cambios; antes del cambio, el mismo `plan` daba `No changes`.
  Lecturas de AWS (sin cambios): ningún nombre del lote existe (alarmas, topic, regla); DLQ con 0 mensajes; RDS con 288
  créditos y ~18,4 GB libres; 5xx de la API con dimensiones `ApiId` y `ApiId, Stage`; métricas de `AWS/Events` de la
  cuenta con la dimensión `RuleName` sola. `pytest tests/ops`: 37 pruebas contra el AWS falso (todo bien; `--solo`;
  `--sin-limpieza`; otra cuenta, sin API, sin INF-2.1 o sin el output, con su código; alarmas, regla y política mal
  configuradas; suscripción pendiente o a otro correo; DLQ con ajenos, las dos con ajenos, en `ALARM` vacía, restos
  viejos y recientes; alarma que no dispara o que no puede avisar; métricas con 8 min de retraso; parada que no es error,
  ECS que ignora o rechaza el `group`, regla sin permiso en el topic, tarea que no se detiene; y `comun.LectorCola` con
  `validate21.py`). `ruff check --line-length 120` sin avisos en `validate31.py`, `comun.py`, `validate21.py` y
  `tests/ops`. TFLint no se pudo ejecutar en local (lo corre `infra.yml`); se revisó a mano lo que exige (tipos,
  descripciones, nada sin usar, `required_providers` del módulo). En `dev`: pendiente (`apply`, confirmar la suscripción
  y `validate31.py`).
- **Pendiente:** el `apply` por `infra.yml` (lo coordina el maestro; no el 2026-10-27, día de campo), confirmar la
  suscripción desde el correo y `validate31.py` en `dev` con la evidencia de C2b y C3c. Sin comprobar hasta entonces:
  que ECS acepte `run-task --group service:worker` y no confunda esa tarea con las del servicio, que EventBridge publique
  con la condición `aws:SourceArn` de la política, el texto exacto de la historia «Action» de una alarma y que el `plan`
  quede vacío tras confirmar la suscripción. Lo de 0.12.0: §5.13 con la imagen de BE-1.1 y la propuesta de R10.

---

## [0.13.1] — 2026-10-25

- **Lote que la motivó:** INF-2.1, antes de validarlo. Decisión del equipo: observar en `dev` el apagado automático y
  el escalado de `worker` no es criterio de cierre.
- **Qué cambió:**
  - PLAN INF-2.1: C2 y C3 pasan a ser criterios de configuración (lo que comprueban C2a y C3a de `validate21.py`) y C4
    se une a C3 (la condición de `embedding` está en la alarma de subida). Observar el comportamiento (C2b, C3b y C4,
    ~1,5 h, casi todo la espera de 45 min de C2b) queda como opcional. El lote se cierra con
    `validate21.py --entorno dev --solo C1,C2a,C3a` (~8 min, antes de las 21:40). C1a ya ejercita parte del apagado:
    encender espera a que la alarma de inactividad, en `ALARM` sin uso, vea `EmbeddingEncendidos`.
  - `validation-2-1.md`: encabezado, nota de cierre, C2b, C3b y C4 marcadas como opcionales, §4 y §5 con las dos
    ejecuciones (cierre y completa).
  - ARCHITECTURE: estado «INF-2.1 aplicado», el rol vinculado de §3.1 ya creado y R13 anota que el apagado por
    inactividad no se observó en `dev` (lo vigila la alarma de INF-3.1).
  - El Terraform, `embedding.py` y `validate21.py` no cambian: la infraestructura sigue aplicada igual y todas las
    comprobaciones siguen en el script.
- **Contratos tocados (§5):** ninguno. Cambian criterios del PLAN y el documento de validación, como en 0.11.1: sube el
  parche.
- **Cómo se verificó:** `AWSServiceRoleForApplicationAutoScaling_ECSService` creado a mano el 2026-10-24; `apply` por
  `infra.yml` sobre `6b6b8e7` (`Apply complete! Resources: 12 added, 0 changed, 0 destroyed.`, 02:34 UTC del 25) y
  `plan -detailed-exitcode` con código 0 después; `embedding.py estado`: `embedding` y `worker` en 0 con rango 0-0,
  `embedding-inactivo` y `worker-colas-vacias` en `ALARM` (lo esperado sin uso), las dos de subida en `OK`, colas en 0 y
  las dos acciones `cron(0 22 * * ? *) America/Bogota`. Una ejecución completa a las 21:36 la detuvo P5 (fuera de
  horario), sin tocar nada. `--solo C1,C2a,C3a` probado contra la simulación de 0.13.0. En `dev`: `validate21.py
  --solo C1,C2a,C3a` con código 0 sobre `684f233` (2026-10-25 16:49–16:56 UTC): pasan P4, P5, P1–P3, C2a, C3a, C1a
  (sano en 5,7 min, con la espera a que la alarma de inactividad, en `ALARM`, viera `EmbeddingEncendidos`) y C1b
  (0,3 min); C3b, C2b y C4, omitidas.
- **Pendiente:** ninguno del lote (INF-2.1 «Hecho»). Opcional: la ejecución completa de `validate21.py` (C2b, C3b y
  C4) o comprobar el apagado por inactividad en el uso normal (`embedding.py estado` y `describe-scaling-activities`
  una hora después de dejar `embedding` sin uso). Lo de 0.12.0: §5.13 con la imagen de BE-1.1 y la propuesta de R10.

---

## [0.13.0] — 2026-10-24

- **Lote que la motivó:** INF-2.1 (encendido de `embedding` y escalado del `worker`).
- **Qué cambió:**
  - Código: en `borde`, el filtro de métricas `campus-locator-dev-localize` (8 recursos); en `computo`, `escalado.tf`
    con 11 recursos (41 en total): objetivos de Application Auto Scaling de `embedding` y `worker` (0-0 al crearse,
    rango ignorado después), tres políticas por pasos de capacidad exacta, cuatro alarmas de expresión y las dos
    acciones de las 22:00; en `envs/dev`, `local.metrica_localize` (la reciben `borde` y `computo`, que así no se
    referencian entre sí) y la variable `apagado_embedding`; `src/ops/embedding.py` y `src/ops/validate21.py`.
  - Nueva ADR-INF-15 con las decisiones: el filtro vive en `borde` y mira `httpMethod` y `path` (se descartó una ruta
    `POST /v1/localize`); «`embedding` encendido» es una muestra de `CPUUtilization` de ECS en el mismo minuto que los
    mensajes, dentro de la alarma de subida de `worker`, porque el apagado por inactividad no puede cambiar el rango de
    `worker`; encender publica `EmbeddingEncendidos` y espera a que la alarma de inactividad lo vea; una política de
    capacidad exacta por sentido, con pasos que cubren todos los valores.
  - §3.1: el rol vinculado `AWSServiceRoleForApplicationAutoScaling_ECSService` no existe; se crea a mano antes del
    `apply` (`validation-2-1` §5, paso 1). §3.4: cómo se enciende y se apaga, la condición de `worker` y el retraso de
    las métricas. §3.8: las alarmas de escalado no avisan. §3.10: CloudWatch pasa de 2,3 a 3,8 USD/mes (16 métricas en
    alarmas y 2 métricas propias); total ≈ 40 y ≈ 53. §4: árbol y fila de INF-2.1 con lo construido. R6: 3–6 min.
  - §5.1: nueva política `campus-locator-dev-worker-colas-vacias` y las métricas propias `LocalizePeticiones` y
    `EmbeddingEncendidos`. §5.3: semántica y validación de `apagado_embedding`. §5.10: contrato de encendido y
    apagado, y parámetros exactos de las alarmas. §5.11: la regla de `embedding` remite al contrato y se documenta
    `embedding.Operador`. §5.12: entradas nuevas de `borde` y `computo`, recursos de `escalado.tf` y por qué el `plan`
    queda vacío.
  - `validation-2-1.md` reescrito con el script: C3 se parte en C3a (configuración) y C3b (comportamiento); §5 con
    Variables, Preparación (incluido el rol vinculado) y Ejecución, y la hora límite para empezar (19:30).
  - PLAN: entregables completos de INF-2.1 y su fila de §3 en «En curso».
  - Corrige contradicciones: (1) `validation-2-1` C3 suponía que el `worker` borra los mensajes de prueba, pero la
    imagen `bootstrap` no consume las colas: ahora los borra el validador y mide la bajada desde que las colas quedan
    vacías. (2) §5.1 tenía una sola política para subir y bajar `worker`; ahora hay una por sentido, cada una con dos pasos
    que fijan su capacidad para cualquier valor (una sola, con pasos distintos por encima y por debajo del umbral,
    dependería de qué muestras agrega Application Auto Scaling). (3) §3.4 y §5.11 daban encender por
    `desiredCount = 1` («lo mismo que `embedding.py encender`»); con la alarma de inactividad eso no basta (§5.10).
    `validate13.py` (INF-1.3) sube `embedding` así: `validation-1-3` §5 dice ahora que se encienda antes con
    `embedding.py`. (4) `validation-2-1` C2b exigía el apagado entre 45 y 60 min desde que se vacían las colas; puede
    llegar un minuto antes (el minuto del vaciado cuenta y `FILL` rellena el último): ahora 43–60, desde el último uso
    (vaciado o encendido). (5) `validation-2-1` P5 pedía el horario siempre; ahora solo con las comprobaciones largas, y
    también exige `worker` en 0. (6) `validation-2-1` §4 decía que las paradas del `worker` podían avisar por la regla
    de EventBridge: con `stopCode = ServiceSchedulerInitiated` no avisan (§3.8). (7) §5.12 decía que INF-2.1 usaría
    los outputs `cluster` y `servicios` de `computo`; el escalado vive dentro del módulo y no los necesita.
- **Contratos tocados (§5):** §5.1 (política y métricas nuevas), §5.3 (`apagado_embedding`), §5.10 (contrato de
  encendido), §5.11 (regla de `embedding`) y §5.12 (módulos). Compatible: sube la menor.
- **Cómo se verificó:** en local, con OpenTofu 1.13.2 y los proveedores `aws` 6.70.0 y `random` 3.9.1 desde un espejo
  en el sistema de archivos (copia sin lock): `fmt -check`, `validate` de `envs/dev` y TFLint 0.65.0 con el *ruleset*
  de AWS 0.50.0 en `envs/dev`, `modules/borde` y `modules/computo`, sin avisos; `tofu test` de `computo` con proveedor
  simulado (6 casos: los 11 recursos con sus nombres, rangos 0-0, expresiones, 45 de 45 y acciones con zona y cron;
  `noche = null` u omitida sin acciones; `inactividad_min` 2 o 45,5 y un cron inválido, rechazados). Con moto 5.2.4 no
  se pudo hacer un `apply`: no implementa las etiquetas de Application Auto Scaling ni el protocolo CBOR de CloudWatch
  del proveedor 6.70. `embedding.py` y `validate21.py` con ruff y contra una simulación acelerada de AWS (ECS con
  tiempos de arranque, métricas por minuto con retraso, alarmas M de N con `FILL` que repiten su acción en `ALARM`,
  capacidad exacta dentro del rango): pasa con 2, 5 y 8 min de retraso de SQS y ECS (C2b a los 44,8 min, bajada de
  C3b a los 14,8); falla como debe con un mensaje ajeno (C3b, C2b y C4, con una sola recepción del ajeno), con la
  alarma de subida sin la condición de `embedding` (C4), sin apagado por inactividad (C2b), fuera de horario o con
  `embedding` en marcha (P5, código 3), sin INF-2.1 y con credenciales inválidas (código 3); `--solo C2a,C3a` no
  cambia nada, C2b y C4 funcionan solas. La simulación destapó que encender justo cuando la alarma iba a pasar a
  `ALARM` lo apagaba al instante: de ahí la espera a que la alarma vea `EmbeddingEncendidos`. Revisión independiente
  del código (contra la documentación de AWS y el código del proveedor 6.70.0), con estos arreglos: las actividades de
  Application Auto Scaling se aceptan también `Pending` o `InProgress` y se buscan 3 min antes de fallar (C3b y C2b
  habrían dado FALLA falsos); C2b y C4 esperan a que SQS cuente 0 tras borrar mensajes que dejó una comprobación
  anterior, y la referencia de C2b es el borrado del último mensaje propio; `EmbeddingEncendidos` se publica con marca
  de tiempo explícita (con el reloj local desfasado, el encendido no la encontraba); cada política tiene dos pasos
  que cubren todos los valores con la misma capacidad (antes, un solo paso dependía de qué muestras agregara
  Application Auto Scaling); y las políticas y acciones de un objetivo se crean en cadena (`depends_on`), porque
  Application Auto Scaling puede rechazar cambios simultáneos y el proveedor no los reintenta. En `dev`: pendiente.
- **Pendiente:** el `apply` y `validate21.py` en `dev` (cierran INF-2.1). Lo de 0.12.0: §5.13 con la imagen de BE-1.1
  y la propuesta de R10 a `BACKEND_FASTAPI`.

---

## [0.12.0] — 2026-10-24

- **Lote que la motivó:** ninguno; cambio aparte antes de INF-2.1. INF-1.4 estaba «Hecho», pero §5 no decía lo que
  `FRONTEND_KOTLIN` y `BACKEND_FASTAPI` necesitan saber del borde.
- **Qué cambió:**
  - Nueva §5.13 «Borde: lo que ve el cliente y lo que recibe `api`»: las respuestas que genera API Gateway (cuerpo
    `{"message": "..."}`, no el formato de error del backend) y lo que llega a `api`, cada fila con si está comprobada.
    Lo comprobado contradice dos supuestos: con `api` en 0 la respuesta es **500** `Internal Server Error`, no 503; y
    no hay 404 de API Gateway, porque `ANY /{proxy+}` también recoge `/`. El corte de los 30 s y las cabeceras que
    añade API Gateway (IP del cliente) quedan sin comprobar; las cabeceras, «a verificar con la imagen de BE-1.1».
  - §5.2: `api_base_url` con su valor real (`https://fuzq99kddb.execute-api.us-east-1.amazonaws.com`) y la nota de que
    cambia si se recrea la API (R8). §3.3 enlaza §5.13.
  - §3.1: el rol vinculado `AWSServiceRoleForAPIGateway` lo creó `root` a mano antes del `apply` de INF-1.4 (no
    existía); queda anotado como recurso fuera de Terraform.
  - R10: el límite de intentos de inicio de sesión lo tiene que poner el backend (propuesta abajo); si limita por IP,
    depende de la cabecera sin verificar de §5.13.
- **Contratos tocados (§5):** §5.13 (nueva) y §5.2 (valor real de `api_base_url`). Contrato nuevo: sube la menor.
- **Cómo se verificó:** el 2026-10-24 a las 20:13 (Bogotá), con `api` en 0 (`desiredCount = runningCount = 0`):
  `curl` a `/` y a `/v1/health` (500, `content-type: application/json`, `apigw-requestid`); 100 `POST /v1/auth/login`
  con 50 en paralelo (62 × 500, 38 × 429 `Too Many Requests`); `POST /v1/localize` de 11 000 000 bytes (413
  `Request Entity Too Large`) y de 9 000 000 (500). `logs filter-log-events` de los dos `requestId` del paso 1: los dos
  con `routeKey = ANY /{proxy+}`, `status = 500` e `integrationStatus = "-"`, también el de `path = /`. CloudTrail
  (`lookup-events` de `CreateServiceLinkedRole`): `ops.apigateway.amazonaws.com` creado por `Root` a las 23:16 UTC; el
  intento del `apply` a las 23:22 UTC dio `InvalidInputException`.
- **Pendiente:**
  - Comprobar el corte de los 30 s y las cabeceras que recibe `api` con la imagen de BE-1.1, y completar §5.13.
  - Proponer a `BACKEND_FASTAPI` un límite de intentos de inicio de sesión (R10). El *throttling* de API Gateway no
    sirve para eso: es aproximado (a 2 req/s configuradas pasaron ~8 a ~21 req/s de una sola máquina, §3.3) y es uno
    para todos los clientes de la ruta, así que no distingue cuentas y, si un atacante lo agota, también deja fuera al
    administrador. 2 req/s ya son ~170 000 intentos al día. Solo el backend sabe a qué cuenta va el intento y si falló.
    Propuesta: por correo, tras 5 fallos en 15 min, responder 429 con `Retry-After` durante 15 min. La respuesta es la
    misma exista o no el correo, con el mismo tiempo (hash de comparación aunque el correo no exista). Los fallos se
    guardan en PostgreSQL, porque la infraestructura no tiene Redis y la memoria de `api` se pierde en cada despliegue.
    Cada bloqueo queda en el log. El límite por IP, solo cuando se verifique la cabecera con la IP del cliente
    (§5.13). Va en el §5 del backend (códigos de error de login) y lo consume la app (mensaje para el 429).

---

## [0.11.1] — 2026-10-24

- **Lote que la motivó:** INF-1.4 (Borde HTTPS), primera ejecución de `validate14.py` en `dev`.
- **Qué cambió:**
  - §3.3: el *throttling* de API Gateway es aproximado («best effort», repartido entre nodos), con la medición contra
    login; sirve para frenar volumen, no como límite de intentos de inicio de sesión. §5.10 y R10 lo anotan; R10 añade
    la fuerza bruta contra `/v1/auth/login` y deja pendiente proponer un límite de intentos al backend.
  - §5.11: la imagen de prueba responde 404 en otros `GET` y **501** en los demás métodos (`POST` incluido); decía solo
    «404 en lo demás». También el docstring de `pruebas/imagen-prueba/servidor.py` (comentario; la imagen publicada no
    cambia).
  - PLAN INF-1.4 C2, `validation-1-4.md` C2b y `validate14.py`: login a 20 req/s durante 10 s con al menos el 10 % de
    429 (antes, 5 req/s durante 20 s con el 25 %). Con 5 req/s la primera ejecución dio 1 de 100 con 429 aunque la
    etapa tenía 2/5 (C2a pasó) y las 100 peticiones entraron por `POST /v1/auth/login` (Logs Insights sobre
    `/campus-locator/dev/apigw`). Medido después: 23 % a 10 req/s, 34 % a 20 y 57 % a 50.
- **Contratos tocados (§5):** ninguno; aclaraciones de §5.10 y §5.11 (valores configurados y respuestas de la imagen
  de prueba sin cambios). Sube el parche.
- **Cómo se verificó:** `stats count(*) by routeKey, status` en Logs Insights (`POST /v1/auth/login` 501 × 99, 429 × 1;
  `ANY /{proxy+}` 200 × 101); `get-stage` con `DefaultRouteSettings` 20/40 y `RouteSettings` de login 2/5; medición
  puntual a 10, 20 y 50 req/s con `.validacion/medir429.py` (no versionado). `validate14.py` con ruff. En `dev`:
  `validate14.py` con código 0 sobre `13d80fe` (C2b: 127 de 200 con 429 en login; 100 × 200 en `/v1/health`).
- **Pendiente:** ninguno del lote (INF-1.4 «Hecho»). Proponer a `BACKEND_FASTAPI` un límite de intentos de inicio de
  sesión (R10).

---

## [0.11.0] — 2026-10-24

- **Lote que la motivó:** INF-1.4 (Borde HTTPS).
- **Qué cambió:**
  - §3.3: el VPC Link en las dos subredes públicas con el grupo `-vpclink`, el *log group* de la API y `prevent_destroy`.
  - §4: el lote INF-1.4 describe lo construido (módulo `borde`, 7 recursos).
  - §5.10: los valores del formato de los *access logs* son **cadenas** (`"status":"200"`, `"-"` si falta un dato), para
    que toda línea sea JSON válido también en un 429; quien calcule con `integrationLatency` (INF-2.1, BE-3.2) la
    convierte a número.
  - §5.12: `computo` tiene la salida nueva `cloud_map_api_arn`; nueva tabla del módulo `borde` (entradas, salidas,
    nombres internos y por qué el `plan` queda vacío); `module.borde` y el output `api_base_url` en los nombres de
    `envs/dev`.
  - `validation-1-4.md`: orden de las precondiciones (P3 primero, como el script), C1b comprueba la imagen `bootstrap`
    y espera la tarea `HEALTHY`, C3a también la retención y los campos del formato, C3b admite `--solo` sin C1b y
    `status` como cadena; §5 «Cómo ejecutarlo» con Variables, Preparación y Ejecución, como `validation-1-2`/`1-3`.
  - PLAN: entregables de INF-1.4 completos y su fila de §3 en «En curso».
- **Contratos tocados (§5):** §5.10 (aclaración del tipo de los valores del formato) y §5.12 (salida
  `cloud_map_api_arn` de `computo`, módulo `borde`). `api_base_url` (§5.2) se crea con el nombre ya documentado.
  Compatible: sube la menor.
- **Cómo se verificó:** en local con OpenTofu 1.10.6 y los proveedores de §5.12 desde un espejo: `fmt -check`,
  `validate` de `envs/dev` y una prueba con proveedor simulado (`tofu test`) que renderiza los 7 recursos de `borde`
  (formato con los diez campos, `api_base_url` sin barra final, la validación de dos subredes y `prevent_destroy`, que
  impide destruir la API); TFLint 0.65.0 con el *ruleset* de AWS 0.50.0 en `envs/dev`, `modules/borde` y
  `modules/computo`, sin avisos; `validate14.py` con ruff, su ruta de credenciales inválidas (código 3), C1a, C2a y C3a
  contra moto server, y la ráfaga de C2b contra un servidor local con *token bucket* 2/5 (56 de 100 con 429; 100 × 200
  en la ruta general). En `dev`: `apply` por `infra.yml` (7 recursos) y `plan` vacío después; la primera
  ejecución de `validate14.py` falló en C2b (lo corrige 0.11.1).
- **Pendiente:** ninguno (INF-1.4 se cerró con 0.11.1).

---

## [0.10.0] — 2026-10-24

- **Lote que la motivó:** INF-1.3 (Cómputo).
- **Qué cambió:**
  - §4: el lote INF-1.3 describe lo construido (módulo `computo`, 30 recursos). Los *log groups* de los cinco procesos
    pasan de `observabilidad` (INF-3.1) a `computo`, porque ECS no arranca una tarea cuyo *log group* no existe; el de
    la API va en `borde` (INF-1.4). §3.8 lo anota.
  - §5.12: `main.tf` de `envs/dev` admite además `data "terraform_remote_state" "bootstrap"`, de donde sale
    `limite_roles_arn` (los dos roles de CI leen todo el bucket de estado, `bootstrap/permisos.tf`); nueva tabla del
    módulo `computo` (entradas, salidas, nombres internos y por qué el `plan` queda vacío).
  - §5.3: `imagen_inicial_tag` se declara con INF-1.3 y se aclara su efecto (solo crea revisiones nuevas).
  - §5.11: la imagen de prueba trae `python` (lo usan los *health checks*), corre como 10001 y se publica a mano tras
    el `apply` (`pruebas/imagen-prueba/README.md`); qué pasa cuando la política de ECR la expira.
  - R11: estado de la limpieza y qué confirmar antes del `apply` de INF-1.3.
  - `validation-1-3.md`: C5 antes de C6 (orden del script), C4 comprueba los **seis** outputs de `bootstrap` (decía
    cinco; §5.2 lista seis) y el *boundary* de los cinco roles de ECS; nota sobre la espera a `HEALTHY`.
  - PLAN: entregables de INF-1.3 completos y su fila de §3 en «En curso».
  - Código: comentario de las ventanas de RDS en `modules/datos/main.tf` sin el horario de `dev` (pendiente de 0.8.0 y
    0.9.0; no cambia recursos).
- **Contratos tocados (§5):** §5.3 (aclaración de `imagen_inicial_tag`), §5.11 (imagen de prueba) y §5.12
  (`terraform_remote_state`, módulo `computo`). Los outputs de §5.2 de INF-1.3 se crean con los nombres ya
  documentados. Compatible: sube la menor.
- **Cómo se verificó:** en local con OpenTofu 1.10.6 y los proveedores de §5.12 desde un espejo: `fmt -check`,
  `validate` de `envs/dev` y una prueba con proveedor simulado (`tofu test`) que renderiza las cinco definiciones de
  tarea; TFLint 0.65.0 con el *ruleset* de AWS 0.50.0 en `envs/dev` y `modules/computo`, sin avisos; `servidor.py`
  probado en local (puertos, `app.cli`, SIGTERM); `validate13.py` con ruff y su ruta de credenciales inválidas
  (código 3). En `dev`: `apply` por `infra.yml` (30 recursos), `plan` vacío después (`-detailed-exitcode` = 0) y `validate13.py` con código 0 sobre `a0f2dc5` (C5 aceptaba solo `t`; `'SSL=' || ssl` da `true`: corregido en ese commit).
- **Pendiente:** ninguno del lote (INF-1.3 «Hecho»). Ya resuelto de 0.8.0: la carpeta se llama `SERVICE_EMBEDDING`.

---

## [0.9.0] — 2026-10-24

- **Lote que la motivó:** ninguno; decisión del equipo antes de INF-1.3. La cuenta tiene cupo 0 de instancias G
  (`L-DB2E81BA` = 0) y no hay tiempo de esperar el aumento.
- **Qué cambió:**
  - Nueva ADR-INF-14: `embedding` vuelve a Fargate con **2 vCPU / 4 GB** y el modelo pasa a **DINOv2 ViT-S/14**
    (vectores de 384; `SERVICE_EMBEDDING` ADR-EMB-11). Se conserva el encendido de 0.7.0: apagado por defecto, a mano y
    con apagado automático tras 45 min sin uso y a las 22:00. ADR-INF-13 queda descartada sin haberse aplicado;
    ADR-INF-05, ADR-INF-06 y ADR-INF-11 lo anotan.
  - Desaparece todo lo de la GPU: proveedor de capacidad, grupo de autoescalado, plantilla de lanzamiento, rol y perfil
    de instancia `campus-locator-dev-ec2-gpu`, grupo de seguridad `-gpu-host`, variable `gpu_tipo_instancia`,
    `EMBEDDING_DEVICE`, el despliegue con `minimumHealthyPercent = 0` y los riesgos R14 y el cupo de R9.
  - `src/ops/gpu.py` pasa a llamarse **`src/ops/embedding.py`** (`encender`, `apagar`, `estado`) y la variable
    `apagado_gpu`, **`apagado_embedding`**. INF-2.1 pasa a «Encendido de `embedding` y escalado del `worker`».
  - §3.4: tabla de tareas (`embedding` 2 vCPU / 4 GB), arranque de 2–3 min. §3.10: costos con `embedding` en Fargate
    (≈ 39 USD/mes con 40 h encendido, ≈ 52 con 160 h). R1, R6, R9 y R13 actualizados.
  - PLAN: INF-1.3 ya no tiene «Requiere decidir antes» (sin cupo de GPU ni perfiles de instancia) y su C6 comprueba la
    tarea en Fargate con 2 vCPU y 4 GB. `validation-1-3.md` (sin P4 ni C6b), `validation-2-1.md` y
    `validation-3-1.md` siguen el cambio; los plazos de encendido bajan de 15 a 10 min.
- **Contratos tocados (§5):** §5.1 (fuera los nombres de la GPU), §5.3 (`apagado_gpu` → `apagado_embedding`; fuera
  `gpu_tipo_instancia`), §5.4 (`TORCH_NUM_THREADS = 2`; fuera `EMBEDDING_DEVICE`), §5.7 (fuera `-gpu-host`), §5.8 (fuera
  `ec2-gpu`), §5.9, §5.10 y §5.11. Nada de esto estaba aplicado: sube la menor.
- **Cómo se verificó:** cupo consultado con `service-quotas get-service-quota --quota-code L-DB2E81BA` (0.0). Revisión
  de dinov2-small en Hugging Face (`SERVICE_EMBEDDING` CHANGELOG 0.5.0). La estimación de latencia escala la medición de
  referencia de ADR-INF-13 por el cómputo de ViT-S/14; no se midió en Fargate.
- **Pendiente:** medir la latencia real (EMB-3.1, BE-3.2). Si se pidió el aumento de cupo de GPU, se puede dejar o
  cancelar: no se usa. El comentario de las ventanas de RDS en `modules/datos/main.tf` (se corrige en INF-1.3).

---

## [0.8.0] — 2026-10-24

- **Lote que la motivó:** ninguno; ajustes al diseño de 0.7.0 al llevar la GPU a los documentos del backend (0.4.0),
  de embeddings (0.4.0) y de la app (0.3.1).
- **Qué cambió:**
  - §3.4 y ADR-INF-13: el grupo de autoescalado de la GPU pasa de 0–1 a **0–2** instancias. La segunda solo existe
    mientras una tarea suelta que pide GPU (validadores y `benchmark.py` de embeddings) coincide con el servicio
    encendido; sin eso, la medición o la validación tendrían que apagar el servicio.
  - R9, PLAN (INF-1.3, «Requiere decidir antes») y `validation-1-3.md` P4: el cupo recomendado de instancias G sube a
    8 vCPU; con 4 (el mínimo, que P4 sigue exigiendo) se avisa en lugar de fallar.
  - §3.4, §4 y §5.10: `gpu.py apagar` y la acción de las 22:00 también dejan `worker` en 0 (capacidad máxima 0 hasta
    el siguiente `gpu.py encender`), aunque queden mensajes: antes podía quedar encendido días esperando a la GPU.
    Nueva acción programada `campus-locator-dev-worker-apagar-noche`; PLAN INF-2.1 (entregables y C1) y
    `validation-2-1.md` (C1b y C2a) la incluyen.
  - §5.11 (Reglas): los validadores que necesitan `embedding` lo encienden si está apagado y lo dejan como lo
    encontraron; las tareas sueltas con GPU no necesitan el servicio.
  - §3.4: corregida la frase «se apaga con `gpu.py apagar`, solo tras 45 min…» (se apaga a mano o solo).
- **Contratos tocados (§5):** §5.1 (acción programada nueva), §5.10 (escalado de `worker`), §5.11 (regla nueva para
  los validadores). Todos compatibles: sube la menor.
- **Cómo se verificó:** revisión cruzada de las cuatro carpetas: ninguna referencia a «horario de `dev`», «06:00»,
  «Fargate» para `embedding` o «PyTorch en CPU» en `dev` fuera del historial de los CHANGELOG.
- **Pendiente:** el comentario de las ventanas de RDS en `modules/datos/main.tf` todavía habla del horario de `dev`
  (se corrige en INF-1.3; no cambia recursos). Renombrar la carpeta `SERVICE_EMBEDDINGS_DINOV2` a `SERVICE_EMBEDDING`,
  el nombre que usan todos los documentos (incluido el disparador de `embedding.yml` en §3.9).

---

## [0.7.0] — 2026-10-24

- **Lote que la motivó:** ninguno; decisión del equipo antes de INF-1.3: `POST /v1/localize` debe responder en menos
  de 1 s.
- **Qué cambió:**
  - Nueva ADR-INF-13: `embedding` corre en GPU, en ECS sobre EC2 (proveedor de capacidad con un grupo de autoescalado
    de 0 a 1 `g4dn.xlarge` bajo demanda), apagado por defecto; se enciende a mano (`src/ops/gpu.py`, INF-2.1) y se
    apaga solo tras 45 min sin peticiones a `/v1/localize` ni mensajes en las colas, y a las 22:00. Reemplaza a
    ADR-INF-06 (CPU) y modifica ADR-INF-05 y ADR-INF-11. Motivo: con 1 vCPU, 5 fotos tardan ~5,5 s a 224 px y ~47 s
    a 518 px (más que los 30 s de API Gateway); una T4 las procesa en decenas de milisegundos. Como prueban 1–3
    personas a ratos, una GPU con horario fijo pasaría casi todo el tiempo ociosa: se paga solo lo encendido.
  - §2 (diagrama y objetivo de latencia: p95 ≤ 1 s en el servidor), §3.2 (la instancia GPU en `publica-a`; la tarea
    de `embedding` sin IP pública), §3.4 (cómputo, encendido y apagado, `worker` solo con `embedding` encendido), §3.7,
    §3.8, §3.10 (≈ 59 USD/mes con 40 h de GPU; ≈ 124 con 160 h), §4, riesgos R1 (también: la cuenta se comparte con
    trend-analyzer), R6 y R9, y nuevos R13 (la GPU no se apaga) y R14 (sin capacidad `g4dn.xlarge`).
  - PLAN: el objetivo de la Fase 3 incluye el segundo; INF-1.3 añade la capacidad GPU, su criterio C6 y dos cosas que
    decidir antes (cupo de instancias G y permisos de perfiles de instancia en `bootstrap`); INF-2.1 pasa de horario
    fijo a encendido manual con apagado automático y depende también de INF-1.4 (la métrica de uso sale de los
    *access logs*); INF-3.1 cambia la alarma de CPU de `embedding` por «encendido más de 10 h»; INF-6.1 añade
    *warm pool* o Spot para la GPU. `validation-1-3` (P4, C2, C6a–C6b), `validation-2-1` (reescrito) y
    `validation-3-1` (P2, C1a) siguen esos criterios.
- **Contratos tocados (§5):** §5.1 (capacidad GPU, rol y perfil `campus-locator-dev-ec2-gpu`, grupo `-gpu-host`,
  alarmas `embedding-inactivo` y `embedding-encendida`, política `embedding-apagar`, filtro `localize` y acción
  `embedding-apagar-noche`; desaparecen las cuatro acciones de horario y la alarma `embedding-cpu`), §5.3
  (`horario_encendido` → `apagado_gpu`; nueva `gpu_tipo_instancia`), §5.4 (`TORCH_NUM_THREADS = 3`, nueva
  `EMBEDDING_DEVICE = cuda`; la imagen trae CUDA y los pesos del modelo), §5.7 (grupo `-gpu-host`), §5.8 (rol de
  instancia con el *boundary*), §5.9 (despliegue de `embedding` con una sola GPU), §5.10 (encendido, escalado de
  `worker`, alarma y latencia objetivo). Es incompatible para `SERVICE_EMBEDDING` (imagen y variable nuevas) y cambia
  el objetivo de latencia del backend: sube la menor.
- **Cómo se verificó:** precios de lista consultados el 2026-10-24 (`g4dn.xlarge` bajo demanda 0,526 USD/h; en Spot
  desde ~0,32 USD/h, descartado por los cortes y porque con pocas horas ahorra poco). Tiempos de CPU medidos con un
  ViT-B/14 en numpy (pesos aleatorios: el tiempo no depende de ellos) en un núcleo de un Xeon de 2,1 GHz con AVX-512;
  los de GPU son estimaciones que confirma EMB-3.1. Sin código: nada se ha aplicado.
- **Pendiente:**
  - Pedir el cupo de instancias G (≥ 4 vCPU, `L-DB2E81BA`) antes de INF-1.3, y leer `bootstrap/permisos.tf` al
    empezarlo.
  - Lotes en otras carpetas: `SERVICE_EMBEDDING` (imagen con CUDA y pesos dentro, `EMBEDDING_DEVICE`, las 5 fotos en
    un lote), `BACKEND_FASTAPI` (objetivo p95 ≤ 1 s, tiempo de espera hacia `embedding`, qué hace `worker` si
    `embedding` se apaga) y `FRONTEND_KOTLIN` (reducir las fotos antes de subirlas; mensaje para el `503` mientras la
    GPU arranca).

---

## [0.6.0] — 2026-10-24

- **Lote que la motivó:** INF-1.2 (datos y secretos).
- **Qué cambió:**
  - Módulo `datos`: RDS PostgreSQL 17 (`db.t4g.micro`, `us-east-1a`, 20→50 GB `gp3` cifrados, privada, grupo de
    subredes `campus-locator-dev-db`, grupo de parámetros `campus-locator-dev-pg17` con `rds.force_ssl = 1`, copias 7
    días, *snapshot* final y `deletion_protection`); bucket del dataset (SSE-S3, *Block Public Access*,
    `BucketOwnerEnforced`, sin versionado ni CORS, multiparte abortada a los 7 días, notificación `dataset/*.jpg` →
    `ingesta` creada después de la política de la cola); colas `ingesta` y `purga` con sus DLQ y la política de
    `ingesta` limitada al bucket y a la cuenta.
  - Módulo `secretos`: `random_password` (base, 40 alfanuméricos; admin inicial, 24), `random_bytes` (JWT, 64 bytes en
    base64) y los tres secretos de §5.4. `datos` y `secretos` se usan entre sí a través de `envs/dev` sin ciclo.
  - `envs/dev`: variables `rds_clase`, `rds_gb`, `rds_gb_max` y `pg_version`; proveedor `hashicorp/random ~> 3.7`;
    outputs `bucket_dataset`, `sqs_*_url`, `rds_endpoint` y `secretos`.
  - Decisiones nuevas: política del bucket que deniega toda petición sin TLS (como el bucket de estado);
    `engine_version` solo con la mayor (RDS elige y actualiza la menor, sin diferencias en el `plan`); ventanas de copia
    y mantenimiento fuera del horario de `dev`; cifrado en reposo de RDS; `apply_immediately` en `dev`; secretos
    recuperables 7 días; `purga` y las DLQ sin política de recurso.
  - Corrige contradicciones: (1) INF-0.2 C4 deja a cada lote comprobar las etiquetas de lo que crea y
    `validation-1-2` no lo hacía: nuevo criterio C6 en el PLAN y en el validador. (2) §5.12 decía añadir un proveedor
    con `init -upgrade`, que además sube `aws` dentro de `~> 6.70`; ahora `init` sin `-upgrade` (`-upgrade` solo para
    actualizar, en su propio cambio). (3) `validation-1-2` devolvía los mensajes ajenos a la cola en cuanto los leía y
    seguía leyendo hasta 120 s: el mismo mensaje se podía recibir muchas veces en una ejecución y, con
    `maxReceiveCount = 5`, acabar en la DLQ; ahora quedan ocultos hasta el final (una recepción por ejecución), y el
    `s3:TestEvent` que deja la notificación se borra. (4) C2 podía pasar sin notificación alguna; ahora exige que haya
    llegado el evento de C1 (control positivo). (5) `validation-1-2` listaba P1 y P2 sin decir que P2 (credenciales)
    va primero, como pide §5.11. (6) §3.5 decía que RDS admite `:5432` desde el grupo de `migrate`, que no existe:
    `migrate` usa el de `api` (§5.7). (7) `validation-1-2` no tenía la preparación (inventario, lock, `plan`, *push*,
    aprobación del `apply` y «plan vacío») que sí tiene `validation-1-1`. (8) §5.3 daba `pg_version = "17"` como
    «versión menor ≥ 17.1»: es solo la mayor. (9) C3b leía `rds.force_ssl` con `--source user`, pero un valor igual al
    de por defecto (en PostgreSQL 17 lo es) puede figurar como `system`: ahora se lee sin filtrar. (10) C5 no comprobaba
    los atributos de la instancia de §3.5 (clase, `gp3`, cifrado, protección contra borrado, copias): nuevo C5d, y el
    criterio C5 del PLAN los nombra.
  - El «plan vacío» tras el primer `apply` (paso 6 de la preparación) dio una diferencia perpetua en
    `aws_db_parameter_group`: `rds.force_ssl = 1` es el valor por defecto en PostgreSQL 17, RDS lo devuelve como
    `Source = system` y `ApplyMethod = pending-reboot`, y la configuración decía `immediate`. Ahora declara
    `apply_method = "pending-reboot"` (sin efecto: el valor es 1 en los dos casos). Lo mismo confirma el cambio de C3b
    (leer sin `--source user`).
  - Tras la revisión independiente, el validador además: no lee `ingesta` si tiene mensajes en proceso, retrasados o
    más de 10 visibles, y no sube nada si entre los visibles hay alguno ajeno (lo devuelve) o si el servicio `worker`
    está en marcha (desde INF-1.3), para no gastar reintentos de mensajes reales; solo borra claves de prueba de su
    propio sello o de otro con más de 15 min (no las de otra ejecución en curso); registra cada objeto antes de subirlo;
    clasifica todo un lote de mensajes antes de borrar; da código 3 (no 2) a un error transitorio de AWS en las
    precondiciones; y la limpieza de la cola no deja de devolver los ajenos aunque falle la lectura.
- **Contratos tocados (§5):** §5.1 (grupo de subredes y *snapshot* final de RDS), §5.2 (outputs que aparecen con
  INF-1.2), §5.3 (variables de INF-1.2; `pg_version` es solo la mayor), §5.4 (formato de los valores y `valueFrom`),
  §5.5 (política «solo TLS»), §5.6 (`purga` y DLQ sin política; `s3:TestEvent`), §5.10 (ventanas de RDS), §5.11 (forma
  de un validador que crea datos) y §5.12 (módulos `datos` y `secretos`; cómo añadir un proveedor al lock). §3.5 y
  §3.6 añaden cómo destruir con un *snapshot* final previo y cómo recrear un secreto en su plazo de recuperación.
- **Cómo se verificó:** `validate12.py --entorno dev` con código 0 sobre `e5ee713` (2026-10-24 18:32–18:34 UTC): pasan
  P1–P2, C1–C2 (evento en 1 s), C3a–C3b, C4 (PostgreSQL 17.9), C5a–C5d y C6 (11 recursos). El `apply` lo hizo
  `infra.yml` (`Resources: 24 added`) tras la aprobación del entorno `dev`; el `plan` siguiente dio la diferencia de
  `rds.force_ssl` descrita arriba y, corregida, `infra.yml` aplicó sin cambios. Lock: `aws` 6.70.0 (sin cambios) y
  `random` 3.9.1. Antes de entregar, sin Terraform ni acceso a AWS en el entorno de pruebas: con OpenTofu 1.11.1, aws
  6.70.0 y random 3.9.1, `fmt -check`, `validate` y TFLint 0.65 + *ruleset* aws 0.50 limpios en `envs/dev`,
  `modules/datos` y `modules/secretos`; `tofu test` de `envs/dev` con proveedores simulados (sin ciclo entre `datos` y
  `secretos`); y un `tofu apply` completo de `envs/dev` contra AWS simulado (moto 5.2.4: 53 recursos, 29 de la red y 24
  de este lote). El validador, con el `comun.py` real, contra ese estado en 35 escenarios: camino feliz; restos y
  `s3:TestEvent`; mensajes ajenos (vuelven con una sola recepción); cola con 12 mensajes (no la lee); `worker` en
  marcha; notificación sin sufijo, sin prefijo o ausente; RDS pública; regla `0.0.0.0/0`; `rds.force_ssl = 0`;
  PostgreSQL 17.0 y 17.10; sin protección contra borrado; JWT de 32 bytes; `port` como texto; secreto ausente; ningún
  valor de secreto en la salida; CORS; ciclo de vida que expira; política con `Allow` o ausente; visibilidad equivocada;
  política de `ingesta` sin condición; `purga` con política; etiqueta ausente; sin la red (código 2); perfil inexistente
  y `--solo` inválido (código 3); alias `--solo C5`; `--sin-limpieza` y la ejecución siguiente. Lo que moto no reproduce
  (sin TLS no se puede subir con la política «solo TLS»; etiquetas al crear el bucket; versión menor) se ajustó en el
  estado simulado. Revisión independiente del Terraform y del validador: sin defectos de exposición en Terraform; sus
  hallazgos sobre el validador están corregidos (ver arriba) y los de destrucción quedan documentados en §3.5 y §3.6.
- **Pendiente:** P2 muestra que los validadores se ejecutan con credenciales del usuario raíz (`…:root`), contra la
  higiene de §3.1 (raíz sin llaves de acceso; un administrador con MFA): crear ese usuario o rol, pasar a él el perfil y
  borrar las llaves del raíz. El «plan vacío» de INF-1.2 es un paso manual de la preparación (`validation-1-2` §5, paso
  6), no una comprobación del validador: el próximo validador que lance un `plan` une las dos variantes de
  `validate02.py` y `validate11.py` en `comun.py` (§5.12). Inventario y limpieza de lo que lista R11 antes de INF-1.3.

---

## [0.5.1] — 2026-10-24

- **Lote que la motivó:** ninguno; inventario de los restos del intento anterior (R11) antes de INF-1.2.
- **Qué cambió:** R11 y la nota de INF-1.2 en PLAN §3 recogen el inventario: la nota decía que el bucket
  `campus-locator-dev-dataset-648617469176` existía y ya no existe. Nada choca con INF-1.2; lo que queda por revisar
  afecta a INF-1.3 (Cloud Map, ECS, ECR, roles) y a costos.
- **Contratos tocados (§5):** ninguno.
- **Cómo se verificó:** `s3 ls`, `rds describe-db-instances`, `describe-db-snapshots`, `describe-db-parameter-groups`,
  `describe-db-subnet-groups`, `sqs list-queues --queue-name-prefix campus-locator` y
  `secretsmanager list-secrets --include-planned-deletion` con el perfil de administración, 2026-10-24.
- **Pendiente:** inventario y limpieza de lo que lista R11 antes de INF-1.3.
- **Historial reescrito (mismo día):** el correo de autor de los commits estaba mal (erratas y uno de la máquina), así
  que se reescribió `main` con `git filter-repo --mailmap`, sin cambiar el contenido. Los hashes citados en este
  archivo y en PLAN §3 se actualizaron: `b20a62f` → `fbe68f8` (INF-0.1), `c677aeb` → `fad2b6b` (INF-0.2) y `ff1cce2` →
  `4c04040` (INF-1.1). Los informes de `.validacion/` y los PR #4 y #5 conservan los hashes viejos.

---

## [0.5.0] — 2026-10-24

- **Lote que la motivó:** INF-1.1 (red y grupos de seguridad).
- **Qué cambió:**
  - Módulo `red`: VPC, cuatro subredes calculadas desde `cidr_vpc` (las /24 número 0, 1, 10 y 11), Internet Gateway,
    tablas propias `-publica` y `-privada` (la principal queda sin usar), endpoint de S3 en la pública y los cinco
    grupos de §5.7 sin reglas en línea (cada regla es un `aws_vpc_security_group_*_rule`).
  - Decisión nueva: el grupo `default` de la VPC se adopta con `aws_default_security_group` y queda sin reglas
    (endurece R2: lo que se cree sin grupo explícito no tiene tráfico).
  - `envs/dev`: `local.prefijo`, variables `cidr_vpc`, `az_computo` y `az_secundaria` (§5.3) y outputs
    `subredes_tareas` y `sg_migrate` (§5.2 ya decía que aparecen con el lote que crea su recurso).
  - §5.12 documenta las entradas, salidas y recursos del módulo `red`, para que INF-1.2 a INF-1.4 lo usen sin leer su
    código; §5.11 completa la API de `comun.py` (qué recibe `Validador`, `Resultado`, `comprobar_cuenta`, patrones de
    Terraform), leída de sus firmas.
  - Corrige contradicciones: INF-0.2 C4 deja a cada lote comprobar las etiquetas de lo que crea y `validation-1-1` no
    lo hacía (nuevo C2e, que también comprueba `Name`); `validation-1-1` listaba P1 antes que P2 aunque §5.11 pide
    evaluar primero las credenciales (ahora P2 va primero); y su §5 no tenía la preparación (inventario de VPC,
    comprobaciones locales, `push`, aprobación del `apply` y variables de GitHub) que `validation-0-2` sí tiene. Además: C3 incluye el `default` sin reglas (C3b), nuevo C5
    para los dos outputs, y P1 hace `init -lockfile=readonly` para no tocar el lock versionado.
- **Contratos tocados (§5):** §5.1 (nombres del IGW, las tablas y el endpoint; `Name` del `default`; etiqueta `Name` en
  los recursos de red), §5.2 (cuándo aparecen `subredes_tareas` y `sg_migrate`), §5.3 (`cidr_vpc` y `az_secundaria`
  nuevas; `az_computo` ya se usa), §5.7 (`default` sin reglas; las reglas solo viven en `red`; solo ASCII en las
  descripciones), §5.9 (formato de `SUBREDES_TAREAS` y `SG_MIGRATE`), §5.11 y §5.12 (documentación de lo existente).
- **Cómo se verificó:** `validate11.py --entorno dev` con código 0 sobre `4c04040` (2026-10-24 15:40–15:41 UTC): pasan
  P1–P2 y C1–C5 (C2a–C2e, C3a–C3b). El `apply` lo hizo `infra.yml` (`Resources: 29 added`) tras la aprobación del
  entorno `dev`; antes hubo que cancelar una ejecución de `main` de un commit ya sobrescrito que esperaba aprobación y
  retenía la fila de concurrencia (§3.9 y el paso 4 de `validation-1-1` §5 lo explican ahora). Variables del repositorio
  `SUBREDES_TAREAS` y `SG_MIGRATE` creadas desde los outputs (§5.9). Antes de entregar, con OpenTofu 1.13.2 y el proveedor aws 6.70.0 (en el entorno
  de pruebas no hay Terraform): `fmt -check`, `validate` y TFLint 0.65 + *ruleset* aws 0.50 limpios en `envs/dev` y
  `modules/red`; `tofu test` del módulo con proveedor simulado (CIDR, zonas, asociaciones, ruta al IGW, endpoint, las
  nueve reglas con sus referencias, outputs, `default` sin reglas y rechazo de una CIDR que no es /16). El validador,
  contra EC2/S3/STS simulados (moto) y un `terraform` simulado en 21 escenarios: red correcta; `plan` con cambios, sin
  credenciales o con el bloqueo ocupado; regla abierta a internet; `default` con reglas; privada con ruta al IGW; NAT;
  endpoint también en la privada; sin DNS; zona equivocada; falta una etiqueta; falta una regla; output equivocado; dos
  VPC con el mismo nombre; sin estado de `dev`; `init` fallido; perfil inexistente; `--solo`; `--solo` inválido;
  salida normal. Y tres interrupciones durante el `plan`: un Ctrl+C, dos Ctrl+C más un SIGTERM, y el validador muerto
  con SIGKILL; en las tres terraform termina y suelta el bloqueo. Revisión independiente del módulo y del validador:
  sin hallazgos de seguridad. Se corrigió lo que encontró en el validador: Ctrl+C en Windows (ahora CTRL_BREAK a un
  grupo de procesos propio), señales repetidas durante la espera, salida a tuberías que daba SIGPIPE si Python moría,
  código de P1 (un fallo local de `init` es 3, no 2) y endpoints borrados que EC2 sigue listando.
- **Pendiente:** lo de 0.3.0 (la limpieza de R11 sigue antes de INF-1.2). `validate02.py` y `validate11.py` tienen dos
  variantes del `plan` interrumpible con SIGINT (§5.12): unirlas en `comun.py` con el próximo validador que lo necesite.

---

## [0.4.1] — 2026-10-24

- **Lote que la motivó:** ninguno; que el próximo lote (INF-1.1) pueda trabajar sin leer el código de INF-0.2.
- **Qué cambió:** §5.9 documenta lo fijo de `infra.yml` (jobs, pasos, marca del comentario, versiones) del que depende
  `validate02.py`; nueva §5.12 con las convenciones del código de Terraform: qué va en cada archivo de `envs/dev`, los
  nombres que ya existen (`data.aws_caller_identity.actual`, `data.aws_default_tags.actuales`, los seis `module.*`), cómo
  se escriben los módulos, cómo se añade un proveedor al lock, qué hace fallar a CI y las ayudas propias de
  `validate02.py`.
- **Contratos tocados (§5):** ninguno nuevo; §5.9 y §5.12 describen lo que ya existía desde INF-0.2 (`fad2b6b`).
- **Cómo se verificó:** cada nombre y valor se copió de los archivos de INF-0.2 validados en `fad2b6b`.
- **Pendiente:** lo mismo que en 0.3.0.

---

## [0.4.0] — 2026-10-24

- **Lote que la motivó:** INF-0.2 (esqueleto de `envs/dev` y CI de Terraform).
- **Qué cambió:**
  - `envs/dev`: *backend* S3 con `use_lockfile` y también `allowed_account_ids`; proveedor `aws ~> 6.70` con
    `allowed_account_ids` y `default_tags`; `data "aws_caller_identity"` (output `cuenta_id`) y
    `data "aws_default_tags"` (deja en el estado las etiquetas efectivas, que comprueba el validador); los seis módulos,
    vacíos, ya compuestos en `main.tf`; `.terraform.lock.hcl` versionado.
  - `infra.yml`: Terraform fijado a la versión del equipo (1.16.6, para que `fmt` y `plan` den lo mismo en
    local y en CI), TFLint con `project/.tflint.hcl`, acciones fijadas
    por SHA, `plan` comentado en el PR (un comentario que se actualiza), PR desde *forks* sin `plan`, concurrencia (un
    `plan` por PR; los `apply` de `main` en fila) y disparo también por cambios en el propio `infra.yml` (§3.9).
  - §5.3: cada variable de `envs/dev` se declara con el lote que la usa.
  - `validation-0-2`: nueva P6 (copia local con `init`), P5 avisa si la versión local no es la de CI, C1–C2 se
    hacen por la API de GitHub (sin `gh pr merge` ni `gh run watch`, que tocan o dependen de la copia local), C4b lee
    las etiquetas efectivas de `data.aws_default_tags`, y la limpieza cancela los `apply` de ejecuciones anteriores que
    quedaron esperando aprobación. Corrige una contradicción: C3b usaba `terraform console` para retener el bloqueo,
    pero desde Terraform 1.15 `console` ya no lo toma; ahora el validador crea su propio `.tflock` (escritura
    condicional, como Terraform) y lo borra solo si sigue siendo suyo. C2a ya no fusiona si `main` avanzó o tiene otra
    ejecución activa, para no aprobar cambios ajenos, y la limpieza de restos ignora PR de *forks* o de otros autores. Su §5 describe además la preparación (lock de
    proveedores, comprobaciones locales y aprobación del primer `apply`), que antes solo se mencionaba.
  - Nuevo riesgo R12: repositorio público, logs y comentarios del `plan` visibles.
- **Contratos tocados (§5):** §5.3 (aclaración, sin cambio de nombres). Los workflows (§3.9) amplían su disparador de
  forma compatible.
- **Cómo se verificó:** `validate02.py --entorno dev` con código 0 sobre `fad2b6b` (2026-10-24 14:04–14:10 UTC): pasan
  P1–P6 y C1–C4b, con el PR de prueba #5 comentado, fusionado y aplicado por `infra.yml` tras la aprobación del entorno
  `dev`; el primer `apply` de `envs/dev` también lo hizo `infra.yml`. Antes de entregar, con OpenTofu 1.13.2 y el
  proveedor aws 6.70.0 (no había Terraform en el entorno de pruebas): `fmt -check`, `validate` y TFLint 0.65 + *ruleset* aws 0.50 limpios en `envs/dev`, `modules/` y
  `bootstrap/`; actionlint + shellcheck limpios en `infra.yml`; el script del comentario probado con node; el
  validador, de principio a fin contra S3/STS/IAM simulados (moto, con escrituras condicionales) para P1–P6 y C3–C4, y
  contra un `gh` simulado en 12 escenarios para C1–C2 (restos anteriores, plan con cambios o fallido, `main` protegida,
  sin permiso de aprobación, `apply` fallido, *scopes* que faltan, variables distintas, sin estado, bloqueo ajeno,
  cuenta equivocada, `--solo C2`, dos ejecuciones seguidas). Revisión independiente de `infra.yml`, `envs/dev` y el
  validador contra el código de Terraform 1.16.6: encontró el cambio de `console` y los riesgos de C2a y de la limpieza
  de restos (corregidos y probados de nuevo en los escenarios «main avanzó», «main ocupada», «padre distinto», PR de
  *fork* y C3b interrumpida).
- **Pendiente:** lo mismo que en 0.3.0.

---

## [0.3.1] — 2026-10-23

- **Lote que la motivó:** ninguno; preparar INF-0.2 sin que nadie tenga que leer el código de `project/`.
- **Qué cambió:** §5.11 documenta la API de `project/src/ops/comun.py` (clase `Validador`, excepciones y ayudas de
  `gh`, Terraform y AWS) y la forma de un validador de esta carpeta.
- **Contratos tocados (§5):** ninguno nuevo; §5.11 describe ayudas que ya existían desde INF-0.1.
- **Cómo se verificó:** la tabla se escribió desde el código de `comun.py` que validó INF-0.1 (`fbe68f8`).
- **Pendiente:** lo mismo que en 0.3.0.

---

## [0.3.0] — 2026-10-23

- **Lote que la motivó:** INF-0.1 (bootstrap de la cuenta), al construirlo, revisarlo y aplicarlo.
- **Qué cambió:**
  - El repositorio (`Ang3l1485/Proyecto_4U`, público) usa el formato inmutable de GitHub para el claim `sub`, así que GitHub firma sus
    tokens OIDC con el `sub` inmutable `repo:propietario@ID/repo@ID:…`. Nueva variable `github_ids` en `bootstrap` y
    los *trust policies* se escriben con `<sub_repo>` (§5.8).
  - Una revisión independiente encontró que `gha-terraform` podía crear un rol propio con `"Action": "*"` y asumirlo.
    Nuevo *permissions boundary* `campus-locator-limite-roles`, obligatorio en todo rol que cree `envs/dev`, y
    denegaciones explícitas en `gha-terraform` (ADR-INF-12).
  - `gha-terraform-plan` puede leer los secretos `campus-locator/dev/*`: sin eso, el `plan` de los PR fallaría desde
    INF-1.2 al refrescar `aws_secretsmanager_secret_version`. No amplía la exposición (el rol ya leía el estado, que
    contiene esos valores); R5 se reescribe para decirlo.
  - Las variables del repositorio y el entorno `dev` de GitHub los crea `bootstrap/configurar_github.py`. En un
    repositorio personal solo puede ejecutarlo su dueño, igual que el validador de INF-0.1 (lee las variables).
  - `project/pyproject.toml`, `project/src/ops/comun.py` y `project/.gitignore` pasan de INF-0.2 a INF-0.1: el
    validador de INF-0.1 no corre sin ellos.
  - Decididos `github_repo`, `correo_alertas` y `github_ids` (§5.3).
  - Nuevo riesgo R11: recursos de un intento anterior siguen en la cuenta y chocan con nombres de §5.1.
- **Contratos tocados (§5):** §5.1 (boundary `campus-locator-limite-roles`), §5.2 (output `limite_roles_arn` de
  `bootstrap`), §5.3 (`github_ids`; valores de `github_repo` y `correo_alertas`), §5.8 (formato del `sub`, permisos de
  `gha-terraform-plan` y `gha-terraform`, boundary), §5.11 (`-dirty` en el informe y cuenta dueña del repositorio en
  los validadores de esta carpeta).
- **Cómo se verificó:** `validate01.py --entorno dev` con código 0 sobre `fbe68f8` (2026-10-24 00:11 UTC): pasan
  P1–P5 y C1–C5, y C2 confirma el `sub` inmutable con un token real. Antes: revisión independiente del Terraform y del
  validador, formato de HCL con `hclwrite` y el validador probado de principio a fin con AWS simulado (moto) en 12
  escenarios. El proveedor OIDC ya existía (intento anterior, 2026-10-14) y se importó al estado de `bootstrap`.
- **Pendiente:**
  - Limpiar los recursos del intento anterior antes de INF-1.2 (R11): clúster ECS `campus-locator-dev-cluster` y sus
    servicios, ECR `campus-locator-dev/*`, *snapshots* de RDS `campus-locator-dev-db*`, buckets
    `campus-locator-dev-dataset-648617469176`, `campus-locator-dev-scans-648617469176` y `4uproject-eafit-tfstate`,
    secreto `campus-locator-dev/jwt-secret`, *namespace* de Cloud Map, *target group*, *log groups* `/ecs/…` y roles
    `campus-locator-dev-backend-*` y `campus-locator-dev-embedding-*`. El rol `campus-locator-github-ci` (equivalente a
    administrador, con comodín en el `sub`) se borró a mano el 2026-10-23.
  - `validation-0-1` da código 2 a P4 y P5, que son entregables del propio lote, pero §5.11 reserva el 2 para «otro
    lote no está listo». Decidir si pasan a código 1.
  - *Cost Anomaly Detection* (§3.8) no lo crea ningún lote.

---

## [0.2.0] — 2026-10-23

- **Lote que la motivó:** ninguno; cambio de organización del monorepo pedido por el equipo.
- **Qué cambió:**
  - El código de la carpeta irá en `project/` y la documentación en `docs/`, con una carpeta nueva
    `docs/validation/` (un documento por lote) y un validador por lote en `project/src/ops/validate<fase><n>.py`.
  - Los lotes se renumeran como `<PREFIJO>-<fase>.<n>` para que el nombre de su validación coincida con el lote
    (`validation-2-2.md` ↔ `validate22.py` ↔ lote x-2.2).
  - El PLAN separa las dependencias «para construir» de las «para validar», numera los criterios de cierre (C1, C2…)
    y añade a §3 las columnas «Validación» y «Última validación».
  - Nuevo §5.11: **contrato común de los validadores** de las cuatro carpetas (nombres, ejecución, códigos de salida
    0–3, informe JSON, reglas de datos de prueba), más la imagen de prueba `bootstrap` y la tarea de validación
    `campus-locator-dev-validacion` para comprobar desde dentro de la VPC.
  - La comprobación de `CREATE EXTENSION vector` pasa de INF-1.2 a INF-1.3 (necesita la tarea de validación, que se crea
    con el cómputo); INF-1.2 comprueba en su lugar la versión del motor.
  - La regla de EventBridge de §3.8 solo avisa por tareas de los **servicios** (`group = service:…`): las tareas
    sueltas de `migrate`, `validacion` y de los validadores ya no generan falsas alarmas.
  - Se fija el nombre de los *streams* de log (`<proceso>/app/<id-de-la-tarea>`) para que los validadores encuentren
    el log de una tarea suelta.
  - Tras escribir los documentos de validación: el entorno `dev` de GitHub se crea en INF-0.1 (no en INF-0.2) y solo
    admite la rama `main`, así un PR no puede usar `gha-terraform`; INF-0.1 C3–C5 se reescriben (Budgets no pide
    confirmación de correo; la de SNS pasa a INF-3.1 C1); INF-0.2 añade `data "aws_caller_identity"` y el output
    `cuenta_id`; INF-1.3 C4 solo exige los outputs que ya existen.
  - Se nombran las alarmas, la política y las acciones de escalado, la regla de EventBridge, el entorno de GitHub y los
    workflows (§5.1); se fija el formato de los *access logs* y el umbral de almacenamiento en GiB (§5.10).
  - Las variables de entrada dicen en qué archivo van (`bootstrap` o `envs/dev`); `bootstrap` expone `github_repo`.
  - La imagen de prueba ignora el comando de la tarea (sale con 0 si es `app.cli`); ECS Exec queda activado solo en
    `api`; la tarea `validacion` aparece en la tabla de cómputo.
  - Contrato de validadores: credenciales o variables que faltan dan código 3 (no 2); cada documento puede declarar
    argumentos propios (`--video`); el prefijo `validacion-` se aplica a lo que el validador nombra y los datos reales
    que usa se quedan.
- **Contratos tocados (§5):** §5.1 (familia `campus-locator-dev-validacion`, log group `/campus-locator/dev/validacion`,
  formato de los *streams* de log y nombres de alarmas, escalado, regla de EventBridge, entorno de GitHub y workflows),
  §5.2 (`familias_tarea` incluye `validacion`; `github_repo`, `cuenta_id` y en qué lote aparece cada output), §5.3
  (columna «Dónde»), §5.4 (el secreto `db` también lo usa la tarea de validación; cómo se usa el secreto `jwt`), §5.5
  (prefijo nuevo `evaluacion/`), §5.7 y §5.8 (la tarea de validación usa el grupo `-api` y el rol de `migrate`; el
  *trust policy* de `gha-terraform` queda ligado a la regla de ramas del entorno `dev`), §5.9 (`Dockerfile` en
  `<CARPETA>/project/` y workflows disparados solo por cambios en `project/`), §5.10 (formato de *access logs*, umbral
  en GiB), §5.11 (nuevo).
- **Equivalencia de identificadores** (las entradas anteriores usan los viejos): INF-01 → INF-0.1 · INF-02 → INF-0.2 ·
  INF-03 → INF-1.1 · INF-04 → INF-1.2 · INF-05 → INF-1.3 · INF-06 → INF-1.4 · INF-07 → INF-2.1 · INF-08 → INF-3.1 ·
  INF-09 → INF-6.1.
- **Cómo se verificó:** comprobación automática de que los lotes citados existen, de que las referencias cruzadas entre
  secciones resuelven, de que cada documento de validación cubre una vez cada criterio de su lote y de que las tablas
  están bien formadas.
- **Pendiente:** escribir los validadores (cada lote los entrega con su código).


---

## [0.1.0] — 2026-10-23

- **Lote que la motivó:** ninguno; planificación inicial del sistema en AWS (previa a INF-01).
- **Qué cambió:** primera versión del documento. Sustituye al «plan inicial» al que apuntaba el `README.md` raíz.
  Decisiones tomadas con el equipo: solo AWS, cuenta propia `648617469176`, región `us-east-1`, entorno único `dev`,
  una sola zona de disponibilidad, sin NAT Gateway, presupuesto de 100 USD/mes, ingesta asíncrona y localización
  síncrona, RDS PostgreSQL + pgvector, JWT propio, GitHub Actions con OIDC y estado de Terraform en S3. ADR-INF-01 a
  ADR-INF-11 y riesgos R1–R10.
- **Contratos tocados (§5):** todos nuevos — nombres (§5.1), outputs (§5.2), variables de entrada (§5.3), variables
  de entorno y secretos (§5.4), bucket (§5.5), colas y topic (§5.6), red y DNS interno (§5.7), IAM (§5.8), despliegue
  (§5.9) y parámetros operativos (§5.10). La sección de contratos pasa de §4 (según el `README.md` anterior) a §5, y
  ya no concentra los contratos de todo el monorepo: cada carpeta es dueña de los suyos (§1.3).
- **Cómo se verificó:** revisión cruzada de nombres contra `BACKEND_FASTAPI/docs/ARCHITECTURE.md` v0.1.0 y
  `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` v0.1.0. Precios de lista de `us-east-1` consultados el 2026-10-23 (Fargate,
  RDS `db.t4g.micro`, IPv4 pública). Requisitos comprobados en documentación de AWS: pgvector 0.8.0 en RDS
  PostgreSQL ≥ 17.1; la integración de API Gateway HTTP API con Cloud Map exige registros SRV cuando ECS registra las
  tareas. Sin código: nada se ha aplicado. Antes de publicar esta versión se aplicó una revisión independiente de
  coherencia entre carpetas: ruta propia para
  el *throttling* del login, `s3:ListBucket` sobre el ARN del bucket con condición de prefijo, rol de solo lectura
  `gha-terraform-plan` para los PR, regla de EventBridge en lugar de una alarma que exigía *Container Insights*, se
  quitó `PORT` de las variables inyectadas (ningún servicio la leía) y se corrigió el orden de creación de la
  notificación S3 → SQS.
- **Pendiente:** definir `github_repo` y `correo_alertas`; medir el costo real tras INF-07 y ajustar la tabla de §3.10.
