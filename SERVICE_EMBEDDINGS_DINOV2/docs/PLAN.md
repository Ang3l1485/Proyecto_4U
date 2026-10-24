# PLAN — Servicio de embeddings (`SERVICE_EMBEDDING`)

Qué se construye y en qué orden. **Cómo** funciona cada pieza está en [`ARCHITECTURE.md`](./ARCHITECTURE.md);
**por qué y cuándo** cambió algo, en [`CHANGELOG.md`](./CHANGELOG.md); **cómo se comprueba** cada lote, en
[`validation/`](./validation/).

Alineado con `ARCHITECTURE.md` **v0.2.0**.

---

## 1. Cómo usar este plan

- No hay fechas: el orden lo dan las fases y las dependencias.
- **Identificadores:** `EMB-<fase>.<n>`. Su validación es `docs/validation/validation-<fase>-<n>.md` y su script,
  `project/src/ops/validate<fase><n>.py` (EMB-2.1 → `validation-2-1.md` → `validate21.py`).
- **§3 es la única tabla de estado de esta carpeta.** Al cerrar un lote solo se edita su fila en §3.
- **Dos tipos de dependencia** (§2.1): *para construir* y *para validar* (lo que debe estar **Hecho** para ejecutar la
  validación; si falta, el validador termina con código 2 y el lote queda `Bloqueado`).
- **Cerrar un lote:** cumplir sus criterios (C1, C2…); validador con código 0 en los entornos que indica su validación;
  evidencia de las comprobaciones manuales en el PR; actualizar su fila de §3. Si cambia un contrato (o la
  `version_vector`), antes se actualiza `ARCHITECTURE.md` §5 (sube la versión) y se añade la entrada en `CHANGELOG.md`.
- Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11; lo propio de este servicio,
  `ARCHITECTURE.md` §5.8. Orden global entre carpetas: `README.md` raíz.
- Prefijos de otras carpetas: `INF-`, `BE-`, `FE-`. Historias de usuario: catálogo único en
  `FRONTEND_KOTLIN/docs/PLAN.md` §5 (todas son propuestas).
- Definición de «hecho» común, además de la validación: `embedding.yml` en verde (lint, pruebas, vectores dorados).

---

## 2. Fases y lotes

Fases comunes a las cuatro carpetas: `INFRASTRUCTURA_TERRAFORM/docs/PLAN.md` §2.1.

### 2.1 Lotes por fase

| Lote | Nombre | Para construir | Para validar | Validación |
|---|---|---|---|---|
| EMB-1.1 | Servicio base e imagen | — | INF-1.3 | [`validation-1-1`](./validation/validation-1-1.md) |
| EMB-2.1 | Vectorización por lotes (`/v1/embed`) | EMB-1.1 | EMB-1.1 | [`validation-2-1`](./validation/validation-2-1.md) |
| EMB-3.1 | Rendimiento en CPU | EMB-2.1 | EMB-2.1, INF-1.3 | [`validation-3-1`](./validation/validation-3-1.md) |
| EMB-3.2 | Conjunto de evaluación y calibración | EMB-2.1 | EMB-2.1, BE-2.4 (vecinos), un dataset real indexado (FE-2.1 + BE-2.2) y el conjunto de fotos de consulta | [`validation-3-2`](./validation/validation-3-2.md) |
| EMB-5.1 | Nueva versión del vector — diferido | EMB-3.2 (solo si una variante gana) | — | — |

### 2.2 Detalle de cada lote

#### EMB-1.1 — Servicio base e imagen
- **Entregables:** estructura de §4.1 en `project/`, `GET /health`, `GET /health/ready`, `GET /v1/info`, carga y
  calentamiento del modelo, `project/Dockerfile` con pesos descargados en el build, `src/ops/comun.py`,
  `.github/workflows/embedding.yml` (contrato de infra §5.9).
- **Decisión a registrar:** la revisión (SHA) de `facebook/dinov2-base`, en ARCHITECTURE §5.3 (sube la versión).
- **Criterios de cierre:**
  - C1. El servicio desplegado en `dev` responde `/health/ready` en < 180 s desde que arranca la tarea.
  - C2. `/v1/info` devuelve `version_vector = dinov2-vitb14/pp-v1` y la revisión fijada.
  - C3. Sin red de salida, el contenedor arranca igual (no descarga nada).
- **Historias:** HU-20.

#### EMB-2.1 — Vectorización por lotes
- **Entregables:** `POST /v1/embed` (§5.2), preprocesamiento pp-v1 (§5.3), cola con prioridad, errores de §5.6,
  vectores dorados.
- **Criterios de cierre:**
  - C1. Los cinco vectores dorados coinciden con tolerancia 1e-5.
  - C2. El vector de una imagen coincide (tolerancia 1e-5) enviada sola o en un lote de 8.
  - C3. Una imagen corrupta en la posición 3 devuelve `400 IMAGEN_INVALIDA` con `detalle.indice = 2`.
  - C4. Con la cola llena de peticiones `baja`, una `alta` se atiende antes que las que esperan.
  - C5. Los límites de §5.6 responden con su código (`413`, `415`, `503 SATURADO`).
- **Historias:** habilita HU-01 y HU-14.

#### EMB-3.1 — Rendimiento en CPU
- **Entregables:** `project/tools/benchmark.py`; resultados en ARCHITECTURE §5.7.
- **Criterios de cierre:**
  - C1. p50 y p95 de lotes de 1, 5 y 8 imágenes medidos en una tarea suelta con la definición de tarea de `dev`.
  - C2. Los números están en ARCHITECTURE §5.7 (sube la versión).
  - C3. Si el lote de 5 supera p95 3 s, la palanca aplicada (§4.4) queda decidida y registrada como ADR.
- **Historias:** habilita HU-01.

#### EMB-3.2 — Conjunto de evaluación y calibración
- **Entregables:** protocolo para tomar las fotos de consulta (puntos conocidos, distintas horas del día), conjunto en
  `evaluacion/` del bucket con el formato de ARCHITECTURE §5.9, `project/tools/evaluacion/` y un informe con
  *recall@1*, *recall@5* a 15 m, distribución de similitudes y comparación de variantes de preprocesamiento.
- **Criterios de cierre:**
  - C1. El conjunto tiene al menos 50 fotos de consulta en 10 puntos con dataset, con su coordenada, y al menos un
    punto con 3 fotos a más de 150 m de toda imagen del dataset (lo usa BE-3.2 C5).
  - C2. El informe incluye *recall@1* y *recall@5* a 15 m y la distribución de similitudes.
  - C3. Los valores recomendados de `LOC_SIM_MIN`, `LOC_SIM_ALTA` y cortes de nivel están entregados a BE-3.2.
- **Historias:** habilita HU-01 y HU-02.

#### EMB-5.1 — Nueva versión del vector (diferido)
- **Alcance:** solo si EMB-3.2 muestra una variante claramente mejor: implementarla con `version_vector` nueva y
  ejecutar el procedimiento de re-indexado de §4.6 junto con el backend.
- **Historias:** HU-01, HU-06.

---

## 3. Estado de los lotes

> **Única tabla de estado.** Valores: `Pendiente`, `En curso`, `Bloqueado`, `Hecho`, `Diferido`. «Última validación» =
> commit corto y fecha de la última ejecución con código 0.

| Lote | Fase | Estado | Validación | Última validación | Versión de ARCHITECTURE al cerrar | Nota |
|---|---|---|---|---|---|---|
| EMB-1.1 | 1 | Pendiente | [1-1](./validation/validation-1-1.md) | — | — | Sin código todavía |
| EMB-2.1 | 2 | Pendiente | [2-1](./validation/validation-2-1.md) | — | — | |
| EMB-3.1 | 3 | Pendiente | [3-1](./validation/validation-3-1.md) | — | — | Latencias de §5.7 sin medir |
| EMB-3.2 | 3 | Pendiente | [3-2](./validation/validation-3-2.md) | — | — | Necesita un dataset real indexado (FE-2.1 + BE-2.2) |
| EMB-5.1 | 5 | Diferido | — | — | — | |

---

## 4. Matriz de trazabilidad

● = el lote entrega la historia · ○ = la habilita (otra carpeta la cierra).

| Historia | EMB-1.1 | EMB-2.1 | EMB-3.1 | EMB-3.2 | EMB-5.1 |
|---|---|---|---|---|---|
| HU-01 Ubicarme con una vuelta | | ○ | ○ | ○ | ● |
| HU-02 Conocer mi ubicación y referencias | | | | ○ | |
| HU-06 Seguimiento continuo | | | | | ○ |
| HU-14 Subir un recorrido | | ○ | | | |
| HU-20 Desplegar automáticamente | ● | | | | |
