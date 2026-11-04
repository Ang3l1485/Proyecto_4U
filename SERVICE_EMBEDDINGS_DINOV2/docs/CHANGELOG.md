# CHANGELOG — Servicio de embeddings (`SERVICE_EMBEDDING`)

Una entrada por versión de [`ARCHITECTURE.md`](./ARCHITECTURE.md), la más reciente primero.

**Cómo se numera la versión del documento**
- **Mayor:** cambio incompatible en la API de §5 (renombrar un campo, quitar un endpoint, cambiar un código de error).
  Mientras la versión sea `0.x`, un cambio incompatible sube la **menor**.
- **Menor:** endpoint o campo nuevo, decisión nueva (ADR), **`version_vector` nueva**, parámetros medidos.
- **Parche:** aclaraciones o correcciones de redacción sin efecto en contratos.

Toda entrada que cambie la `version_vector` lo indica de forma explícita en «Contratos tocados», porque obliga a
re-indexar el dataset.

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

## [0.2.0] — 2026-10-23

- **Lote que la motivó:** ninguno; cambio de organización del monorepo pedido por el equipo.
- **Qué cambió:**
  - El código de la carpeta irá en `project/` y la documentación en `docs/`, con una carpeta nueva
    `docs/validation/` (un documento por lote) y un validador por lote en `project/src/ops/validate<fase><n>.py`.
  - Los lotes se renumeran como `<PREFIJO>-<fase>.<n>` para que el nombre de su validación coincida con el lote
    (`validation-2-2.md` ↔ `validate22.py` ↔ lote x-2.2).
  - El PLAN separa las dependencias «para construir» de las «para validar», numera los criterios de cierre (C1, C2…)
    y añade a §3 las columnas «Validación» y «Última validación».
  - §4.1 describe la estructura nueva (`project/src/app/`, `project/src/ops/`, `project/tools/`).
  - Nuevo §5.8: entornos y datos de prueba de los validadores del servicio (`local` con la misma imagen, `dev` con
    tareas sueltas).
  - Nuevo §5.9: formato de la salida de `benchmark.py`, del conjunto de evaluación (`puntos.json`) y de su informe.
  - EMB-3.2 se valida con BE-2.4 (vecinos) y un dataset real (FE-2.1 + BE-2.2); su conjunto incluye un punto lejos del
    dataset para BE-3.2 C5; el nombre del informe cambia `/` por `_`.
- **Contratos tocados (§5):** §5.5 (la imagen incluye `tools/benchmark.py` para ejecutarlo como tarea suelta;
  `src/ops/`, `tests/` y `tools/evaluacion/` quedan fuera), §5.8 y §5.9 (nuevos); §5.7 aclara que `COLA_MAX_IMAGENES` no
  cuenta el lote en curso. La `version_vector` **no**
  cambia.
- **Equivalencia de identificadores** (las entradas anteriores usan los viejos): EMB-01 → EMB-1.1 · EMB-02 → EMB-2.1 ·
  EMB-03 → EMB-3.1 · EMB-04 → EMB-3.2 · EMB-05 → EMB-5.1.
- **Cómo se verificó:** comprobación automática de que los lotes citados existen, de que las referencias cruzadas entre
  secciones resuelven, de que cada documento de validación cubre una vez cada criterio de su lote y de que las tablas
  están bien formadas.
- **Pendiente:** escribir los validadores (cada lote los entrega con su código).


---

## [0.1.0] — 2026-10-23

- **Lote que la motivó:** ninguno; diseño inicial previo a EMB-01. No hay código.
- **Qué cambió:** primera versión. Modelo DINOv2 ViT-B/14 (768 dimensiones, decisión del equipo) en CPU,
  preprocesamiento
  pp-v1, descriptor CLS normalizado, cola con prioridad, pesos dentro de la imagen. ADR-EMB-01 a ADR-EMB-08 y riesgos
  R1–R7.
- **Contratos tocados (§5):** todos nuevos — convenciones (§5.1), endpoints `/health`, `/health/ready`, `/v1/info`,
  `/v1/embed` (§5.2), modelo y preprocesamiento (§5.3), formato del vector (§5.4), imagen (§5.5), errores (§5.6) y
  parámetros (§5.7). **`version_vector` inicial: `dinov2-vitb14/pp-v1`.**
- **Cómo se verificó:** revisión cruzada con `BACKEND_FASTAPI/docs/ARCHITECTURE.md` v0.1.0 (lote máximo 8, prioridad,
  comprobación de `version_vector`, `vector(768)` con coseno) e `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` v0.1.0
  (puerto 8080, `/health/ready` en el *health check*, 1 vCPU / 3 GB, `TORCH_NUM_THREADS`). Antes de publicar se aplicó
  una revisión independiente: se quitó `PORT` de las variables consumidas, se documentó
  que la prioridad no interrumpe un lote en curso, la igualdad entre tamaños de lote pasa a tolerancia 1e-5 y los
  valores que pertenecen a infra (tamaño de tarea, URL, horario) se referencian en lugar de copiarse.
- **Pendiente:** fijar la revisión del modelo (EMB-01); medir latencias reales (EMB-03).
