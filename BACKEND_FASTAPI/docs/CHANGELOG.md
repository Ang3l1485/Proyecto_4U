# CHANGELOG — Backend (`BACKEND_FASTAPI`)

Una entrada por versión de [`ARCHITECTURE.md`](./ARCHITECTURE.md), la más reciente primero.

**Cómo se numera la versión del documento**
- **Mayor:** cambio incompatible en un contrato de §5 (renombrar un campo, cambiar un código de error, quitar un
  endpoint, cambiar el formato de un mensaje). Mientras la versión sea `0.x`, un cambio incompatible sube la **menor**.
- **Menor:** endpoint, campo opcional, tabla o mensaje nuevos; decisión nueva (ADR); parámetros calibrados.
- **Parche:** aclaraciones o correcciones de redacción sin efecto en contratos.

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
  - §4.1 describe la estructura nueva (`project/src/app/`, `project/src/ops/`, `project/docker-compose.yml` para el
    entorno `local`).
  - Nuevo §5.11: entornos, variables y datos de prueba de los validadores del backend.
  - Lote nuevo **BE-2.4 Diagnóstico de búsqueda** (§4.8): `POST /v1/admin/diagnostico/vecinos` devuelve los `k`
    vecinos crudos de una foto. Lo necesita la evaluación de embeddings (EMB-3.2) para calibrar antes de BE-3.2, y
    BE-3.2 reutiliza su consulta. Las secciones de §4 a partir de BE-3.1 se desplazan un número (§4.9–§4.12).
  - Tras escribir los documentos de validación: `GET /v1/admin/videos` y `GET /v1/admin/videos/{id}` pasan de BE-4.1
    a BE-2.1 (la app los necesita para el progreso de la subida); `complete` hace `HEAD` y pasa a `subida` lo que ya
    está en S3; nuevos comandos `desactivar-usuario` y `limpiar-validacion`, y `crear-usuario` pasa a ser idempotente.
  - BE-2.3 se valida con BE-2.2 y BE-3.1; BE-4.1, con BE-2.4 en lugar de BE-3.2 (su C1 usa el endpoint de vecinos), lo
    que rompe el ciclo BE-4.1 → BE-3.2 → FE-2.1.
  - Se precisan: la clave del JWT se usa como texto; `db = no_configurada` en `/v1/health/ready`; los endpoints
    reservados de admin validan el token antes del `501`; la caché de alertas de la app evalúa la vigencia al anunciar.
  - §5.11: la tarea de validación de infra para leer la base (solo `SELECT`), ECS Exec para BE-3.2 y tabla de limpieza.
- **Contratos tocados (§5):** §5.2 (clave del JWT), §5.3 (`db = no_configurada`, alertas y reservados), §5.4
  (`complete`), §5.5 (endpoint nuevo `POST /v1/admin/diagnostico/vecinos` y lote de cada grupo), §5.6 (`FOTOS_INVALIDAS`
  también en ese endpoint), §5.9 (la imagen se construye desde `project/` y no incluye `src/ops/`; comandos nuevos
  `verificar-esquema` y `crear-usuario`, que sustituye a `crear-admin` y acepta `--rol`), §5.11 (nuevo).
- **Equivalencia de identificadores** (las entradas anteriores usan los viejos; BE-2.4 es nuevo y no tiene equivalente):
  BE-01 → BE-1.1 · BE-02 → BE-1.2 · BE-03 → BE-1.3 · BE-04 → BE-2.1 · BE-05 → BE-2.2 · BE-06 → BE-2.3 · BE-07 → BE-3.1 ·
  BE-08 → BE-3.2 · BE-09 → BE-4.1 · BE-10 → BE-5.1 · BE-11 → BE-5.2 · BE-12 → BE-5.3 · BE-13 → BE-6.1.
- **Cómo se verificó:** comprobación automática de que los lotes citados existen, de que las referencias cruzadas entre
  secciones resuelven, de que cada documento de validación cubre una vez cada criterio de su lote y de que las tablas
  están bien formadas.
- **Pendiente:** escribir los validadores (cada lote los entrega con su código).


---

## [0.1.0] — 2026-10-23

- **Lote que la motivó:** ninguno; diseño inicial previo a BE-01. No hay código.
- **Qué cambió:** primera versión. Define los tres procesos (`api`, `worker`, `migrate`), el flujo de recolección con
  URLs prefirmadas, la ingesta asíncrona, el algoritmo de localización v1 y el borrado con purga. Cierra decisiones
  abiertas que la app tenía pendientes: privacidad de las fotos de ubicación (decisión 7 → ADR-BE-06), borrado de
  videos (decisión 10 → ADR-BE-07), autenticación (decisión 11 → ADR-BE-03) y aplaza el cálculo de rutas (decisión 2
  → ADR-BE-11). Fija el rumbo en norte verdadero [0, 360) para todos los contratos (ADR-BE-12).
- **Contratos tocados (§5):** todos nuevos — convenciones (§5.1), JWT (§5.2), endpoints públicos (§5.3), de
  recolección (§5.4) y de administración (§5.5), errores (§5.6), esquema de la base (§5.7), mensajes de colas
  (§5.8), procesos de la imagen (§5.9) y parámetros (§5.10). Partió de la tabla de «endpoints propuestos» del antiguo
  `FRONTEND_KOTLIN/ARCHITECTURE.md` §3 y la reemplaza. Cambios respecto de esa tabla:
  - todas las rutas llevan el prefijo `/v1`;
  - `POST /collect/videos/{id}/images` ya no recibe las fotos: devuelve URLs prefirmadas y se añade
    `POST /v1/collect/videos/{id}/complete`;
  - las alertas de admin pasan de `POST` + `PUT` a `PUT` idempotente con id del cliente, y se añade
    `POST /v1/admin/alerts/sincronizar`;
  - se añaden `GET /v1/health`, `GET /v1/health/ready`, endpoints de imágenes individuales y en lote, y
    re-procesado.
- **Cómo se verificó:** revisión cruzada de nombres con `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` v0.1.0
  (variables de entorno, colas, bucket, permisos) y `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` v0.1.0 (endpoint,
  dimensión 768, `version_vector`); revisión de compatibilidad con los modelos de la app (`LugarDestino`,
  `CategoriaLugar`, `Alerta`, `ResumenAdmin`, `Sesion`, `EstadoFoto`) descritos en
  `FRONTEND_KOTLIN/docs/ARCHITECTURE.md`
  §5.6. Antes de publicar se aplicó una revisión independiente de coherencia: el `worker` envía a embeddings copias
  reducidas en lotes de 4 (antes, 8 fotos de hasta 4 MB superaban el límite de 16 MB); la foto completa de alertas
  incluye las de vigencia futura; `tipo` de alerta por defecto `otro`; la versión de vector va como literal en la
  consulta (índice parcial) y se comprueba en la primera llamada, no al arrancar; se quitaron ciclos entre lotes.
- **Pendiente:** calibrar los umbrales de localización (BE-08); definir los contratos reservados (`/v1/localize/frame`,
  `/v1/route`, `/v1/eventos`) antes de sus lotes.
