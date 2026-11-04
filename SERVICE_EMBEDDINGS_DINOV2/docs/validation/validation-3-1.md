# Validación 3-1 — EMB-3.1 Rendimiento en CPU

| Campo | Valor |
|---|---|
| Lote | `EMB-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate31.py` |
| Entornos | `dev` (**cierra el lote**). `local` no aplica: la medida exige la definición de tarea de `dev` |
| Criterios | Automáticos: C1 (C1a, C1b) · Manuales: C2, C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.8.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `EMB-2.1` en «Hecho»: la imagen desplegada trae `/v1/embed` y `tools/benchmark.py` | Fila EMB-2.1 de `docs/PLAN.md` §3 en `Hecho`; `ecs describe-services --cluster campus-locator-dev --services embedding` → `taskDefinition` y `networkConfiguration`; `ecs describe-task-definition` → imagen del contenedor `app` con etiqueta SHA, no `bootstrap` |
| P2 | `INF-1.3` en «Hecho»: clúster, familia `campus-locator-dev-embedding` y log group `/campus-locator/dev/embedding` | `ecs describe-clusters --clusters campus-locator-dev` → `status = ACTIVE`; `ecs describe-task-definition --task-definition campus-locator-dev-embedding` sin error; `logs describe-log-groups --log-group-name-prefix /campus-locator/dev/embedding` → un grupo |
| P3 | `AWS_PROFILE` con credenciales de la cuenta `648617469176` | `sts get-caller-identity` → `Account`. Sin variable o con credenciales inválidas: código 3 (§5.11) |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | `ecs run-task --cluster campus-locator-dev --task-definition <revisión de P1> --launch-type FARGATE --started-by validacion-emb31 --network-configuration <la de P1> --overrides '{"containerOverrides":[{"name":"app","command":["python","tools/benchmark.py","--salida","json"]}]}'`; `ecs describe-tasks` cada 15 s hasta `lastStatus = STOPPED` (máx. 30 min) | `containers[app].exitCode = 0`, `taskDefinitionArn` de la familia `campus-locator-dev-embedding`, `cpu = 1024` y `memory = 3072` (tamaño de `dev`, infra §3.4) |
| C1b | Lee el log de esa tarea en `/campus-locator/dev/embedding` (`logs describe-log-streams` → el stream cuyo nombre termina en el ID de la tarea; `logs get-log-events`) y extrae el JSON que imprime `benchmark.py` | Trae p50 y p95 de los lotes de 1, 5 y 8 imágenes, todos > 0 y con p50 ≤ p95. El script copia los seis valores en el `detalle` de C1b del informe |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C2 | Copia los seis valores del `detalle` de C1b a la fila «Latencia objetivo» de ARCHITECTURE §5.7 (quitando «aún sin datos»), sube la versión del documento y añade la entrada en `CHANGELOG.md` | *Diff* de §5.7, de la versión y del `CHANGELOG.md`, y el informe JSON `project/.validacion/EMB-3.1-<AAAAMMDD-HHMMSS>.json` adjunto |
| C3 | El script imprime el p95 del lote de 5. Si supera 3000 ms: elige la palanca siguiendo el orden de §4.4 y la registra como ADR nuevo en §6 (si es ONNX o int8, anota que exige `version_vector` nueva, ADR-EMB-08). Si no lo supera, no aplica | Enlace al ADR en el PR, o el p95 medido con la nota «no aplica» |

## 4. Datos de prueba y limpieza

El servicio no guarda nada (§5.8): no hay datos de prueba. La tarea suelta (`startedBy = validacion-emb31`) termina sola
al acabar `benchmark.py`; si el script se interrumpe o vence el plazo, la detiene con `ecs stop-task`. Al empezar
detiene las que hayan quedado de una ejecución anterior
(`ecs list-tasks --cluster campus-locator-dev --started-by validacion-emb31`). Sus eventos de log quedan en
`/campus-locator/dev/embedding` con la retención de 14 días (infra §5.10).

## 5. Cómo ejecutarlo

```bash
cd SERVICE_EMBEDDING/project
uv run --group ops python src/ops/validate31.py --entorno dev
```

Variables: `AWS_PROFILE` (§5.8). Duración aproximada: 10–20 min (arranque de la tarea, unos 3 min, más la medición;
depende de las repeticiones de `benchmark.py`).
