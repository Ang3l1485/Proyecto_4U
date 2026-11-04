# Validación 1-1 — EMB-1.1 Servicio base e imagen

| Campo | Valor |
|---|---|
| Lote | `EMB-1.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate11.py` |
| Entornos | `dev` (C1) y `local` (C2, C3: el arranque sin red solo se puede forzar ahí). En cada entorno, las comprobaciones del otro quedan `omitida`. **Cierran el lote las dos ejecuciones con código 0**, la de `local` con `EMBEDDING_IMAGEN` = la imagen desplegada que identifica C1a |
| Criterios | Automáticos: C1 (C1a, C1b), C2, C3 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.8.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | (`dev`) `INF-1.3` en «Hecho»: clúster, servicio `embedding` con una revisión de `campus-locator-dev-embedding` y log group `/campus-locator/dev/embedding` | `ecs describe-clusters --clusters campus-locator-dev` → `status = ACTIVE`; `ecs describe-services --cluster campus-locator-dev --services embedding` → sin `failures`; `logs describe-log-groups --log-group-name-prefix /campus-locator/dev/embedding` → un grupo |
| P2 | (`dev`) `AWS_PROFILE` con credenciales de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Sin variable o con credenciales inválidas: código 3 (§5.11) |
| P3 | (`local`) Docker disponible y puerto 8080 libre | `docker info` con código 0; una conexión a `localhost:8080` es rechazada |
| P4 | (`local`) `EMBEDDING_IMAGEN` definida y de plataforma `linux/amd64` (infra §5.9) | `docker pull` (si es de ECR, tras `aws ecr get-login-password`) y `docker image inspect --format '{{.Os}}/{{.Architecture}}'` = `linux/amd64`. Sin variable: código 3 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | (`dev`) Lee `taskDefinition` y `networkConfiguration` de `ecs describe-services --cluster campus-locator-dev --services embedding`, y la imagen del contenedor `app` con `ecs describe-task-definition` | La revisión es de la familia `campus-locator-dev-embedding` y la imagen es `…/campus-locator/embedding:<SHA de 40 caracteres>`, no `:bootstrap` (la imagen de prueba también responde `/health/ready`) |
| C1b | (`dev`) `ecs run-task --cluster campus-locator-dev --task-definition <revisión de C1a> --launch-type FARGATE --started-by validacion-emb11 --network-configuration <la de C1a>`, sin sobrescribir el comando; `ecs describe-tasks` cada 5 s (máx. 10 min) hasta `healthStatus = HEALTHY` | Instante en que se observa `HEALTHY` − `startedAt` < 180 s. Es una cota superior: el *health check* corre cada 30 s (infra §5.7). Falla si la tarea pasa a `STOPPED` o vence el plazo |
| C2 | (`local`) `docker run -d --name validacion-emb11 -p 8080:8080 -e TORCH_NUM_THREADS=1 $EMBEDDING_IMAGEN`; espera `GET http://localhost:8080/health/ready` = 200 (máx. 180 s) y llama a `GET /v1/info` | `version_vector = dinov2-vitb14/pp-v1`, `modelo = facebook/dinov2-base` y `revision` igual al SHA de la fila «Revisión» de ARCHITECTURE §5.3 (falla si allí sigue sin anotarse) |
| C3 | (`local`) `docker run -d --name validacion-emb11-sinred --network none -e TORCH_NUM_THREADS=1 $EMBEDDING_IMAGEN`; como `--network none` no publica puertos, cada 5 s ejecuta con `docker exec` el comando del *health check* de infra §5.7 contra `/health/ready` | El comando termina con código 0 (200 `{"estado": "listo"}`) antes de 180 s desde `docker run` y el contenedor sigue en marcha (`docker inspect` → `State.Running = true`) |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

El servicio no guarda nada (§5.8): no hay datos de prueba que borrar. El script crea una tarea suelta con
`startedBy = validacion-emb11` y los contenedores `validacion-emb11` y `validacion-emb11-sinred`. Al terminar (también
si
algo falló, salvo `--sin-limpieza`) detiene la tarea con `ecs stop-task` y borra los contenedores con `docker rm -f`. Al
empezar hace lo mismo con los restos de una ejecución anterior: las tareas de
`ecs list-tasks --cluster campus-locator-dev --started-by validacion-emb11` y los contenedores con esos nombres.

## 5. Cómo ejecutarlo

```bash
cd SERVICE_EMBEDDING/project
uv run --group ops python src/ops/validate11.py --entorno dev
EMBEDDING_IMAGEN=<ecr_embedding_url>:<sha> uv run --group ops python src/ops/validate11.py --entorno local
```

Variables: `AWS_PROFILE` en `dev` (y en `local` si la imagen es de ECR); `EMBEDDING_IMAGEN` en `local` (§5.8): para
cerrar el lote, la imagen que identifica C1a. Duración aproximada: `dev` 6–10 min (aprovisionar la tarea, descargar
~2 GB, cargar y calentar el modelo); `local` 4–6 min.
