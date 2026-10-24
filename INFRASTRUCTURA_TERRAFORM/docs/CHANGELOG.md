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
    evaluar primero las credenciales (ahora P2 va primero). Además: C3 incluye el `default` sin reglas (C3b), nuevo C5
    para los dos outputs, y P1 hace `init -lockfile=readonly` para no tocar el lock versionado.
- **Contratos tocados (§5):** §5.1 (nombres del IGW, las tablas y el endpoint; `Name` del `default`; etiqueta `Name` en
  los recursos de red), §5.2 (cuándo aparecen `subredes_tareas` y `sg_migrate`), §5.3 (`cidr_vpc` y `az_secundaria`
  nuevas; `az_computo` ya se usa), §5.7 (`default` sin reglas; las reglas solo viven en `red`; solo ASCII en las
  descripciones), §5.9 (formato de `SUBREDES_TAREAS` y `SG_MIGRATE`), §5.11 y §5.12 (documentación de lo existente).
- **Cómo se verificó:** Pendiente: `validate11.py --entorno dev` con código 0 sobre un commit de `main` (se completa al
  cerrar el lote). Antes de entregar, con OpenTofu 1.13.2 y el proveedor aws 6.70.0 (en el entorno
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
- **Contratos tocados (§5):** ninguno nuevo; §5.9 y §5.12 describen lo que ya existía desde INF-0.2 (`c677aeb`).
- **Cómo se verificó:** cada nombre y valor se copió de los archivos de INF-0.2 validados en `c677aeb`.
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
- **Cómo se verificó:** `validate02.py --entorno dev` con código 0 sobre `c677aeb` (2026-10-24 14:04–14:10 UTC): pasan
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
- **Cómo se verificó:** la tabla se escribió desde el código de `comun.py` que validó INF-0.1 (`b20a62f`).
- **Pendiente:** lo mismo que en 0.3.0.

---

## [0.3.0] — 2026-10-23

- **Lote que la motivó:** INF-0.1 (bootstrap de la cuenta), al construirlo, revisarlo y aplicarlo.
- **Qué cambió:**
  - El repositorio (`AlejandroSPosada/4U_project`, público) se creó después del 2026-07-15, así que GitHub firma sus
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
- **Cómo se verificó:** `validate01.py --entorno dev` con código 0 sobre `b20a62f` (2026-10-24 00:11 UTC): pasan
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
