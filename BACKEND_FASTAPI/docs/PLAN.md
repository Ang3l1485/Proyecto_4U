# PLAN — Backend (`BACKEND_FASTAPI`)

Qué se construye y en qué orden. **Cómo** funciona cada pieza está en [`ARCHITECTURE.md`](./ARCHITECTURE.md);
**por qué y cuándo** cambió algo, en [`CHANGELOG.md`](./CHANGELOG.md); **cómo se comprueba** cada lote, en
[`validation/`](./validation/).

Alineado con `ARCHITECTURE.md` **v0.16.1**.

---

## 1. Cómo usar este plan

- No hay fechas: el orden lo dan las fases y las dependencias.
- **Identificadores:** `BE-<fase>.<n>`. Su validación es `docs/validation/validation-<fase>-<n>.md` y su script,
  `project/src/ops/validate<fase><n>.py` (BE-2.2 → `validation-2-2.md` → `validate22.py`).
- **§3 es la única tabla de estado de esta carpeta.** Al cerrar un lote solo se edita su fila en §3.
- **Dos tipos de dependencia** (§2.1): *para construir* (lo que hace falta para escribir el código; casi siempre se
  puede avanzar en `local`) y *para validar* (lo que debe estar **Hecho** para ejecutar la validación en `dev`; si
  falta, el validador termina con código 2 y el lote queda `Bloqueado`).
- **Cerrar un lote:** cumplir sus criterios (C1, C2…); validador en `dev` con código 0; evidencia de las comprobaciones
  manuales en el PR; actualizar su fila de §3. Si cambió un contrato, antes se actualiza `ARCHITECTURE.md` §5 (sube la
  versión) y se añade la entrada en `CHANGELOG.md`.
- Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11; lo propio del backend,
  `ARCHITECTURE.md` §5.11. Orden global entre carpetas: `README.md` raíz.
- Prefijos de otras carpetas: `INF-` (infraestructura), `EMB-` (embeddings), `FE-` (app).
- Historias de usuario: catálogo único en `FRONTEND_KOTLIN/docs/PLAN.md` §5 (todas son propuestas).
- Definición de «hecho» común a todos los lotes, además de su validación: `backend.yml` en verde, endpoints nuevos
  cubiertos por pruebas de contrato contra los esquemas de §5 y sin secretos ni URLs firmadas en los logs.

---

## 2. Fases y lotes

Fases comunes a las cuatro carpetas: `INFRASTRUCTURA_TERRAFORM/docs/PLAN.md` §2.1.

### 2.1 Lotes por fase

| Lote | Nombre | Para construir | Para validar | Validación |
|---|---|---|---|---|
| BE-1.1 | Base del servicio | — | INF-1.3, INF-1.4 | [`validation-1-1`](./validation/validation-1-1.md) |
| BE-1.2 | Base de datos y migraciones | BE-1.1 | BE-1.1, INF-1.2 | [`validation-1-2`](./validation/validation-1-2.md) |
| BE-1.3 | Autenticación | BE-1.2 | BE-1.2 | [`validation-1-3`](./validation/validation-1-3.md) |
| BE-2.1 | Recolección (subida del dataset) | BE-1.3 | BE-1.3 | [`validation-2-1`](./validation/validation-2-1.md) |
| BE-2.2 | Worker de ingesta | BE-2.1 (contrato de EMB-2.1) | BE-2.1, EMB-2.1, INF-2.1 | [`validation-2-2`](./validation/validation-2-2.md) |
| BE-2.3 | Resumen del panel | BE-2.1 | BE-2.2, BE-3.1 | [`validation-2-3`](./validation/validation-2-3.md) |
| BE-2.4 | Diagnóstico de búsqueda (vecinos) | BE-2.2 | BE-2.2 | [`validation-2-4`](./validation/validation-2-4.md) |
| BE-3.1 | Lugares | BE-1.3 | BE-1.3 | [`validation-3-1`](./validation/validation-3-1.md) |
| BE-3.2 | Localización | BE-2.4, BE-3.1 | BE-2.2, BE-2.4, BE-3.1, EMB-3.1, EMB-3.2 y un dataset real del campus (FE-2.1) | [`validation-3-2`](./validation/validation-3-2.md) |
| BE-3.3 | Alertas (fuera del núcleo) | BE-1.3 | BE-1.3, BE-2.3 (para C5) | [`validation-3-3`](./validation/validation-3-3.md) |
| BE-4.1 | Administración de videos e imágenes, y purga | BE-2.2 | BE-2.2, BE-2.4 | [`validation-4-1`](./validation/validation-4-1.md) |
| BE-5.1 | Corrección visual (`/v1/localize/frame`) | BE-3.2 | BE-2.2, BE-4.1 (no el dataset real ni la calibración de BE-3.2: crea sus fotos) | [`validation-5-1`](./validation/validation-5-1.md) |
| BE-5.2 | Eventos de uso y estadísticas — diferido | BE-3.2 | — | — |
| BE-5.3 | Rutas (`/v1/route`) — diferido, no hace falta por ahora (la ruta se calcula en el teléfono) | BE-3.1 | — | — |
| BE-6.1 | Endurecimiento — diferido | Fases 1–4 cerradas | — | — |

### 2.2 Detalle de cada lote

#### BE-1.1 — Base del servicio
- **Entregables:** estructura de §4.1 en `project/`, `config.py`, middlewares (`X-Request-Id`, logs JSON, errores con
  el formato de §5.1), `GET /v1/health`, `GET /v1/health/ready` (sin base todavía: informa `db` como no configurada),
  `project/Dockerfile`, `project/pyproject.toml` (uv, ruff, pytest, grupo `ops`), `project/docker-compose.yml` para el
  entorno `local`, `src/ops/comun.py`; `.github/workflows/backend.yml` según el contrato de infra §5.9 (sin el paso
  `migrate` hasta BE-1.2); `python -m app.worker` provisional, que solo registra latidos (ARCHITECTURE §4.2).
- **Criterios de cierre:**
  - C1. `GET {api_base_url}/v1/health` responde 200 con el `commit` desplegado.
  - C2. Un error forzado devuelve el formato de §5.1 y su `X-Request-Id` aparece en `/campus-locator/dev/api`.
  - C3. `backend.yml` publica la imagen con la etiqueta del commit y actualiza el servicio `api`.
- **Historias:** HU-09, HU-20, HU-22.

#### BE-1.2 — Base de datos y migraciones
- **Entregables:** modelos y migración inicial de §5.7 (tipos, tablas, índices, extensión `vector`, índice HNSW
  parcial), `python -m app.cli migrar`, `python -m app.cli verificar-esquema`, creación idempotente del admin inicial,
  paso `migrate` en `backend.yml`, `/v1/health/ready` con la base.
- **Criterios de cierre:**
  - C1. Dos despliegues seguidos ejecutan `migrate` con salida 0.
  - C2. `verificar-esquema` confirma que la base tiene exactamente el esquema de §5.7.
  - C3. Existe un usuario `admin`.
  - C4. `GET /v1/health/ready` informa `"db": "ok"`.
- **Historias:** habilita HU-10, HU-13, HU-14.

#### BE-1.3 — Autenticación
- **Entregables:** `POST /v1/auth/login`, JWT de §5.2, dependencia `requiere_admin` (en `/v1/admin/*` y
  `/v1/collect/*`), auditoría de intentos, `python -m app.cli crear-usuario` (crea o actualiza y reactiva) y
  `desactivar-usuario` (§5.9), acceso a la base desde la API con `503 BASE_NO_DISPONIBLE` (§4.4) y los endpoints
  reservados de §5.3 respondiendo `501` (`GET /v1/admin/stats/uso` lo usa la validación).
- **Criterios de cierre:**
  - C1. Credenciales válidas devuelven un token con los *claims* de §5.2.
  - C2. «Correo inexistente» y «contraseña incorrecta» dan la misma respuesta `401 CREDENCIALES_INVALIDAS`.
  - C3. Un usuario inactivo no puede entrar.
  - C4. Un token vencido o con la firma alterada da `401` con el código de §5.2.
  - C5. Un token de rol `user` contra una ruta de admin da `403 SIN_PERMISOS`.
  - C6. Cada intento queda en `auditoria` sin la contraseña.
- **Historias:** HU-10.

#### BE-2.1 — Recolección
- **Entregables:** `POST /v1/collect/videos`, `POST /v1/collect/videos/{id}/images` (URLs prefirmadas PUT),
  `POST /v1/collect/videos/{id}/complete` con el paso a `subida` (§4.5, §5.4), `GET /v1/admin/videos` y
  `GET /v1/admin/videos/{id}` (§5.5) para seguir la subida, y `python -m app.cli limpiar-validacion` (§5.9).
- **Criterios de cierre:**
  - C1. Crear un video, pedir URLs y subir 3 JPEG con `PUT` deja los objetos en la clave de infra §5.5.
  - C2. Repetir cada llamada no duplica videos ni fotos.
  - C3. Una URL vencida da 403 y pedirla de nuevo permite completar la subida.
  - C4. `complete` devuelve el conteo por estado, con las fotos ya subidas en `subida` aunque el `worker` esté apagado.
  - C5. `GET /v1/admin/videos/{id}` devuelve el video con sus fotos en orden y el mismo conteo, y
    `GET /v1/admin/videos?q=` lo encuentra por nombre.
  - C6. `limpiar-validacion` borra un video `validacion-` con sus filas y sus objetos de S3, y se niega a borrar un
    video sin ese prefijo.
- **Historias:** HU-14; habilita HU-13.

#### BE-2.2 — Worker de ingesta
- **Entregables:** `python -m app.worker` (ingesta según §4.6 y mensajes de §5.8), miniaturas, estados del video,
  espera a que embeddings esté listo, mensaje `reprocesar_imagen`.
- **Criterios de cierre:**
  - C1. Las fotos subidas quedan `procesada` con vector y miniatura.
  - C2. Un JPEG corrupto queda en `error` con motivo, sin pasar por la DLQ.
  - C3. Con `embedding` apagado los mensajes esperan en la cola y se procesan al encender, sin llegar a la DLQ.
  - C4. Un evento duplicado no crea un segundo vector.
  - C5. `reprocesar_imagen` vuelve a generar el vector de una imagen.
- **Historias:** HU-14.

#### BE-2.3 — Resumen del panel
- **Entregables:** `GET /v1/admin/stats` (§5.5). `alertas_activas` cuenta la tabla `alertas` (la escribe BE-3.3;
  ARCHITECTURE §4.7).
- **Criterios de cierre:**
  - C1. `total_fotos`, `total_lugares` y `ultimo_video` coinciden con los datos de prueba creados por el validador.
    `alertas_activas` se comprueba con datos en BE-3.3 (C5): las alertas salieron del núcleo (decisión del usuario,
    2026-10-25).
- **Historias:** HU-11.

#### BE-2.4 — Diagnóstico de búsqueda
- **Entregables:** `POST /v1/admin/diagnostico/vecinos` (§4.8, §5.5) y la consulta de vecinos sobre el índice parcial
  de la versión activa, que BE-3.2 reutiliza.
- **Criterios de cierre:**
  - C1. Una imagen del dataset enviada como consulta sale como primer vecino, con similitud ≥ 0,95.
  - C2. La respuesta trae `k` vecinos (o todos si el índice tiene menos) ordenados de mayor a menor similitud, sin
    filtrar por `LOC_SIM_MIN`: una imagen sin relación con el dataset también recibe `k` vecinos.
  - C3. `k` fuera de 1–50 da `422 VALIDACION`; una parte que no es JPEG o supera 1,5 MB da `400 FOTOS_INVALIDAS`; un
    token de rol `user` da `403 SIN_PERMISOS`.
  - C4. La foto de consulta no queda en S3 ni en los logs, y no se escribe ninguna fila en `eventos_localizacion`.
- **Historias:** habilita HU-01 (calibración de EMB-3.2 y BE-3.2).

#### BE-3.1 — Lugares
Desde ARCHITECTURE 0.11.0 solo lugares: las alertas pasaron a BE-3.3 (decisión del usuario, 2026-10-25: «no
necesitamos las alertas por el momento»).
- **Entregables:** `GET /v1/places` (§5.3) y el CRUD de lugares de `/v1/admin/places` (§5.5), con su auditoría (§5.7)
  y lo que BE-3.2 necesita de ellos (`servicios.lugares.leer_todos`, `dominio.geo`; ARCHITECTURE §4.9).
- **Criterios de cierre:**
  - C1. Un lugar creado con `POST /v1/admin/places` aparece en `GET /v1/places` y en `GET /v1/admin/places` con los
    campos de §5; editado con `PUT`, las dos lecturas dan los valores nuevos; borrado con `DELETE`, deja de aparecer,
    `PUT` da `404` y repetir el `DELETE` da `204`.
  - C2. Con posición, `GET /v1/places` ordena por `distancia_m` y un lugar guardado en esa posición sale primero con
    `distancia_m` < 1; `categoria` filtra; sin posición, `distancia_m` es `null` y el orden es por nombre.
  - C3. Un lugar con el mismo nombre en mayúsculas, con tildes o con espacios de más da `409 NOMBRE_DUPLICADO`, al
    crear y al editar.
  - C4. Las entradas fuera de §5.3/§5.5 dan `422 VALIDACION`; `/v1/admin/places` exige token (`401` sin él) y
    `GET /v1/places` es público.
  - Que las fotos de un lugar borrado queden con `lugar = null` lo cubren las pruebas con base
    (`tests/base/test_lugares_base.py`): asignar un lugar a una foto llega con BE-4.1.
- **Historias:** HU-15; habilita HU-02 y HU-03.

#### BE-3.3 — Alertas (fuera del núcleo)
Sale de BE-3.1 (ARCHITECTURE 0.11.0); construido en 0.14.0 (ARCHITECTURE §4.11, ADR-BE-10 y ADR-BE-19; contratos en
§5.3 y §5.5). Se revisó con el frontend (FE-3.3 y FE-3.6, que consumen las alertas): el contrato coincide con lo que
espera la app, y lo que la app debe hacer está en ARCHITECTURE §4.11, «Para la app».
- **Entregables:** `GET /v1/alerts` (foto completa y por diferencias con `desde`), `GET /v1/admin/alerts`,
  `PUT /v1/admin/alerts/{id}` (con `If-Match`/versión y `409 CONFLICTO_VERSION`) y `DELETE /v1/admin/alerts/{id}`
  (sin `If-Match`, §5.5), `POST /v1/admin/alerts/sincronizar` (§5.3, §5.5), auditoría `alerta.*` (§5.7) y la
  limpieza diaria de *tombstones* (`ALERTAS_TOMBSTONE_DIAS`, §5.10).
- **Criterios de cierre:**
  - C1. La secuencia «crear, editar, borrar» de una alerta, sincronizada por diferencias, deja la caché del cliente
    igual a la foto completa.
  - C2. `DELETE` de un id desconocido da 204.
  - C3. Una alerta activa con vigencia futura aparece en la foto completa.
  - C4. `sincronizar` aplica cada cambio por separado y devuelve su resultado.
  - C5. `alertas_activas` de `GET /v1/admin/stats` sube en 1 con una alerta activa nueva y no cambia con una inactiva
    (venía de BE-2.3 C1).
- **Historias:** HU-05, HU-16.

#### BE-3.2 — Localización
- **Entregables:** `POST /v1/localize` con el algoritmo de §4.10, `eventos_localizacion`, parámetros calibrados.
- **Calibración:** con el conjunto de EMB-3.2, fijar `LOC_SIM_MIN`, `LOC_SIM_ALTA` y los cortes de nivel, y registrar
  los valores en ARCHITECTURE §5.10 (sube la versión).
- **Criterios de cierre:**
  - C1. En al menos 10 puntos conocidos del campus con dataset, el error mediano es ≤ 15 m.
  - C2. Ninguna respuesta de nivel `alta` tiene error > 30 m.
  - C3. p95 de latencia en el servidor (`integrationLatency` de los *access logs*, infra §5.10) ≤ 1 s con `embedding`
    encendido en `dev`.
  - C4. Ninguna foto de consulta queda en S3, en disco ni en los logs.
  - C5. Fotos de un lugar sin dataset devuelven `200` con `resultado = "sin_coincidencias"`.
  - C6. Los umbrales calibrados están registrados en ARCHITECTURE §5.10.
- **Historias:** HU-01, HU-02, HU-23.

#### BE-4.1 — Administración de videos e imágenes, y purga
- **Entregables:** endpoints de videos e imágenes de §5.5 (salvo los dos `GET` de videos, que llegan con BE-2.1), URLs
  prefirmadas GET, lote eliminar/reasignar, re-procesar, purga en el `worker`, reconciliador en `api`, auditoría.
- **Criterios de cierre:**
  - C1. Tras borrar un video, sus imágenes dejan de salir en la búsqueda desde la llamada siguiente
    (`POST /v1/admin/diagnostico/vecinos`, la misma consulta que usa `/v1/localize`).
  - C2. Los objetos de S3 del video desaparecen tras la purga.
  - C3. Si el `worker` no purga (apagado), el reconciliador re-encola y no quedan objetos huérfanos al volver.
  - C4. Renombrar y borrar quedan en `auditoria`.
  - C5. Los endpoints de §5.5 pasan las pruebas de contrato.
- **Historias:** HU-17, HU-18.

#### BE-5.1 — Corrección visual
Planificado el 2026-10-28 para la meta «Guía en tiempo real (fotos + pasos)» (`PRIORITY-2.md`, fuera del repositorio);
construido en ARCHITECTURE 0.16.0 (§4.14, ADR-BE-21; contrato en §5.3). Lo consume la guía por voz de la app
(**FE-5.3**, vistas 6.5–6.6: cada ~10 m una foto que, si es confiable y coherente con los pasos, reemplaza la posición
del PDR); FE-5.1 (grafo y rutas en el teléfono) no lo necesita.
- **Entregables:** `POST /v1/localize/frame` (§5.3): una foto, su rumbo y la posición previa con un radio (por defecto
  40 m, de 10 a 100; `LOC_FRAME_RADIO_*`, §5.10); búsqueda exacta solo entre las imágenes del radio
  (`buscar_vecinos_en_radio`) y el algoritmo de BE-3.2 sin cambios; respuesta con posición, confianza, nivel, lugar
  cercano, `distancia_previa_m`, `radio_busqueda_m` e `imagenes_en_radio`; `sin_coincidencias` como `200`; fila en
  `eventos_localizacion` con `origen = frame`; `validate51.py`.
- **Criterios de cierre:**
  - C1. Una foto igual a una del dataset, con la posición previa a 15 m de ella, da `resultado = ok` a ≤ 10 m de esa
    foto, nivel `alta` y `distancia_previa_m` coherente (±1 m).
  - C2. La misma foto con la posición previa lejos (a 300 m, fuera del radio máximo) nunca devuelve su ubicación,
    aunque haya otras fotos del dataset dentro del radio.
  - C3. `radio_m` limita la búsqueda: con la previa a 60 m, `radio_m = 30` no la encuentra y `radio_m = 100` sí.
  - C4. Las peticiones mal formadas dan los errores de §5.3 (`422 VALIDACION` con su campo, `400 FOTOS_INVALIDAS` con
    su índice).
  - C5. Cada `200` deja una fila en `eventos_localizacion` con `origen = frame` y `fotos_usadas = 1`; los errores,
    ninguna.
  - C6. `latencia_ms` (servidor) ≤ 1 s en cada respuesta, con `embedding` encendido en `dev`.
- **Umbrales:** usa los `LOC_*` de BE-3.2 (aún iniciales); al calibrarlos cambian aquí sin tocar código (ARCHITECTURE
  §4.14, «Calibración»). El radio y, si hiciera falta, cortes de nivel propios se ajustan con el día de campo de FE-5.3.
- **Historias:** HU-06.

#### BE-5.2 — Eventos de uso y estadísticas (diferido)
- **Alcance:** `POST /v1/eventos` (anónimo) y `GET /v1/admin/stats/uso` para la vista 7.15, incluido el mapa de calor
  de `eventos_localizacion`.
- **Historias:** HU-19.

#### BE-5.3 — Rutas (diferido)
- **Alcance:** modelo del grafo de caminos, cómo se construye (decisión abierta 2 del frontend) y `GET /v1/route`.
- **No hace falta por ahora** (decisión del usuario del 2026-10-27, confirmada el 2026-10-28; `PRIORITY-2.md` §6 decisión 3): el grafo lo entrega
  el equipo (`grafo.json` en los `assets/` de la app) y la ruta más corta se calcula en el teléfono, sin red (FE-5.1).
  Se retoma solo si un día el grafo se sirve desde el backend (el formato no cambiaría). `GET /v1/route` sigue
  respondiendo `501`.
- **Historias:** HU-04 (hoy la entrega FE-5.1).

#### BE-6.1 — Endurecimiento (diferido)
- **Alcance:** pruebas de carga de `/v1/localize`, revisión de seguridad (OWASP API Top 10), límites por cliente si el
  *throttling* de API Gateway no basta, trazas distribuidas, cliente generado desde OpenAPI para la app.
- **Historias:** HU-22.

---

## 3. Estado de los lotes

> **Única tabla de estado.** Valores: `Pendiente`, `En curso`, `Bloqueado` (una precondición de validación no se
> cumple), `Hecho`, `Diferido`. «Última validación» = commit corto y fecha de la última ejecución con código 0 en `dev`.

| Lote | Fase | Estado | Validación | Última validación | Versión de ARCHITECTURE al cerrar | Nota |
|---|---|---|---|---|---|---|
| BE-1.1 | 1 | Hecho | [1-1](./validation/validation-1-1.md) | `2fe5a9d` 2026-10-24 | 0.5.1 | Primer despliegue por `backend.yml` (`api` de 0 a 1 réplica con `campus-locator-dev-api:2`). La primera ejecución destapó que `backend.yml` nunca había llegado al repositorio y que C3a rechazaba un commit que solo tocara el workflow (corregido en 0.5.1) |
| BE-1.2 | 1 | Hecho | [1-2](./validation/validation-1-2.md) | `684f233` 2026-10-25 | 0.6.0 | Primera migración en dev por la tarea `migrate` (`campus-locator-dev-migrate:2`): revisión `0001` sobre PostgreSQL 17.9 y pgvector 0.8.1; `verificar-esquema` coincide, lo que confirma en PostgreSQL 17 los textos del catálogo de `esquema.py` (§4.3, R11). El admin inicial lo creó el paso migrate del despliegue: las dos ejecuciones de C1 dieron `ya_habia_admin` (§5.10) |
| BE-1.3 | 1 | Hecho | [1-3](./validation/validation-1-3.md) | `78bae6d` 2026-10-25 | 0.7.1 | Desplegado por `backend.yml` (`migrate:3`, sin migraciones nuevas). C2: 401 idénticos en 1168 y 1116 ms con 0,25 vCPU (R12). Antes del push, una revisión independiente dio 5 defectos (NUL → 500, cola del hash sin tope, huecos del último admin, limpieza y reintentos del validador), corregidos en el mismo commit. Límite de intentos por cuenta (propuesta de infra 0.12.0, R7): pendiente de decisión |
| BE-2.1 | 2 | Hecho | [2-1](./validation/validation-2-1.md) | `9f6ed19` 2026-10-25 | 0.8.0 | Desplegado por `backend.yml` (`api` y `worker:5` con la misma imagen). `validate21.py --entorno dev` con código 0 (informe `.validacion/BE-2.1-20261025-222036.json`): P1–P5 y C1a–C6b pasan; C3a confirmó el vencimiento de la URL prefirmada (403 «Request has expired», desfase 0 s); C6b sin videos reales para probar la negativa |
| BE-2.2 | 2 | Hecho | [2-2](./validation/validation-2-2.md) | `3b01b68` 2026-10-25 | 0.9.2 | `validate22.py --entorno dev` con código 0 (informe `.validacion/BE-2.2-20261026-005058.json`): P1–P6, C1a (fotos 1–3 en `procesada` en 5,4 min con el `worker` arrancando desde 0), C1b, C1c, C2, C4, C5, C3a y C3b; `embedding` encendido en 172 s y 202 s y apagado al final. Antes, P6 falló dos veces por el validador, no por la infra: `c5917bd` código 3 y `54fdf18` código 2 (`get-instances-health-status` siempre da `InstanceNotFound` porque el servicio de Cloud Map no tiene configuración de salud; 0.9.2 usa `list-instances` con la IP de la tarea) |
| BE-2.3 | 2 | Hecho | [2-3](./validation/validation-2-3.md) | `012e0ae` 2026-10-26 | 0.13.1 | `GET /v1/admin/stats` en una sola sentencia (ARCHITECTURE §4.7; §5.5 detallado sin cambiar la forma de la respuesta, que consume FE-2.2). Pruebas con base en el CI de `backend.yml` del PR 9 (run 40374138268: 874, ninguna omitida; en la máquina no arrancó Docker Desktop); desplegado por el run 40374740872 (`worker:12` con la imagen de `api`). `validate23.py --entorno dev` con código 0 (informe `.validacion/BE-2.3-20261026-182628.json`): P1–P5 (`embedding` encendido en 325 s), C1a (`ingesta` vacía; `total_fotos` 0 → 0 con 2 fotos registradas sin subir → 2 con las dos en `procesada` en 4,6 min), C1b (`total_lugares` 0 → 2 → 1), C1c (`ultimo_video` = el video de prueba, número 8, y `alertas_activas` = 0); limpieza: `embedding` apagado, video (4 objetos) y lugar borrados |
| BE-2.4 | 2 | Hecho | [2-4](./validation/validation-2-4.md) | `50d931d` 2026-10-25 | 0.10.0 | `validate24.py --entorno dev` con código 0 (informe `.validacion/BE-2.4-20261026-020153.json`; el informe registra `17b0acb`, que sobre `50d931d` solo añade docs del frontend; `api`, `migrate` y `worker` con la imagen `backend:50d931d`): P1–P5 (`embedding` encendido en 311 s), C1 (fotos 1–3 en `procesada` en 4,1 min; cada una es su primer vecino con similitud 0,9991, 0,9992 y 0,9996), C2a, C2b, C3a, C3b, C3c, C4a (6 claves nuevas, `eventos_localizacion` sin cambios) y C4b; al final `embedding` apagado, video de prueba borrado y `validacion+user` desactivado. Lo necesita EMB-3.2 |
| BE-3.1 | 3 | Hecho | [3-1](./validation/validation-3-1.md) | `86fc024` 2026-10-25 | 0.11.0 | Solo lugares desde 0.11.0 (las alertas pasaron a BE-3.3, decisión del usuario del 2026-10-25). `validate31.py --entorno dev` con código 0 (informe `.validacion/BE-3.1-20261026-030207.json`; `api` con la imagen `backend:86fc024`): P1–P3, C1a–C1c (crear, editar y borrar; `DELETE` repetido → 204), C2a–C2c (orden por distancia, filtro por categoría y orden por nombre), C3a–C3c (`409 NOMBRE_DUPLICADO` con mayúsculas, tildes y espacios de más), C4a (6 entradas → `422`) y C4b (`401` sin token); limpieza: 3 lugares de prueba borrados. En local, también código 0 contra el compose |
| BE-3.2 | 3 | En curso | [3-2](./validation/validation-3-2.md) | — | — | Construido en 0.12.0 (`POST /v1/localize`, ARCHITECTURE §4.10 y ADR-BE-18; `validate32.py`), probado en local (834 pruebas con la base del compose), sin ejecutar nada en `dev`. Centroide sin ponderar y margen `(p₁ − p₂) / p₁` (ADR-BE-18): confirmados por el usuario el 2026-10-26 (0.12.1). Falta: el dataset real (FE-2.1), el conjunto y el informe de EMB-3.2, la calibración de `LOC_SIM_MIN`, `LOC_SIM_ALTA` y los cortes de nivel (§5.10 dice «Iniciales»: C6 falla hasta entonces) y `validate32.py --entorno dev` con código 0 |
| BE-3.3 | 3 | Hecho | [3-3](./validation/validation-3-3.md) | `4885ad6` 2026-10-26 | 0.14.1 | Fuera del núcleo (decisión del usuario, 2026-10-25). `GET /v1/alerts` con foto completa y diferencias con un margen de 60 s, `/v1/admin/alerts` con `PUT` + `If-Match`, `DELETE` con *tombstone* y `sincronizar` cambio por cambio, auditoría y purga diaria en `api` (ARCHITECTURE §4.11 y ADR-BE-19; construido en 0.14.0, sin migración). Pruebas con base en el CI de `backend.yml` del PR 10 (run 40383029250 sobre `89f6a52`: 1003, ninguna omitida; en la máquina no arrancó Docker Desktop); desplegado por el run 40383733721. `validate33.py --entorno dev` con código 0 (informe `.validacion/BE-3.3-20261026-191602.json`): P1–P4, C1a–C1d (caché por diferencias = foto completa; C1b comprobó que `If-Match` pasa por API Gateway: `409 CONFLICTO_VERSION`), C2, C3, C4 y C5 (`alertas_activas` 2 → 3: s0 incluye F de C3 y A2 de C4); limpieza: 4 alertas borradas (6 *tombstones* hasta el 2027-01-24). En el log de `api`, la primera purga diaria (`alertas_purgadas`, 0 borradas) 60 s después de arrancar. Lo consumirán FE-3.3 y FE-3.6 (ARCHITECTURE §4.11, «Para la app») |
| BE-4.1 | 4 | Hecho | [4-1](./validation/validation-4-1.md) | `c5f6517` 2026-10-27 | 0.15.1 | `PATCH`/`DELETE` de videos, `/v1/admin/images`, URLs GET, purga en el `worker` (en serie con la ingesta) y reconciliador en `api`; sin migración ni cambios de infra (ARCHITECTURE §4.12 y ADR-BE-20). Pruebas con base en el CI del PR 11 y de `main`; `validate41.py --entorno dev` con código 0 (P1–P5, C5b, C4a, C1a, C1b, C4b, C5a, C2, C3). Integrado durante el día de campo por decisión del usuario. Lo consume FE-4.1 |
| BE-5.1 | 5 | Hecho | [5-1](./validation/validation-5-1.md) | `92b9cee` 2026-10-28 | 0.16.1 | Construido en 0.16.0 (`POST /v1/localize/frame`, ARCHITECTURE §4.14 y ADR-BE-21; contrato en §5.3; sin migración ni cambios de infra). Pruebas sin base en verde en local; las de `tests/base/test_frame_base.py`, en el CI del PR 12 (verde). `validate51.py --entorno dev` con código 0 sobre `92b9cee` (2026-10-28; P1–P5, C1–C6; latencia mediana 262 ms en el servidor). El radio (40 m) y los cortes de nivel del frame se ajustan con el día de campo de FE-5.3. Lo consume FE-5.3 |
| BE-5.2 | 5 | Diferido | — | — | — | |
| BE-5.3 | 5 | Diferido | — | — | — | No hace falta por ahora: el grafo lo entrega el equipo y la ruta se calcula en el teléfono (decisión del usuario del 2026-10-27, confirmada el 2026-10-28; FE-5.1) |
| BE-6.1 | 6 | Diferido | — | — | — | |

---

## 4. Matriz de trazabilidad

● = el lote entrega la historia (total o parcialmente) · ○ = la habilita (otra carpeta la cierra).

| Historia | 1.1 | 1.2 | 1.3 | 2.1 | 2.2 | 2.3 | 2.4 | 3.1 | 3.2 | 3.3 | 4.1 | 5.1 | 5.2 | 5.3 | 6.1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HU-01 Ubicarme con una vuelta | | | | | ○ | | ○ | | ● | | | | | | |
| HU-02 Conocer mi ubicación y referencias | | | | | | | | ○ | ● | | | | | | |
| HU-03 Elegir destino | | | | | | | | ○ | | | | | | | |
| HU-04 Ser guiada hasta el destino | | | | | | | | | | | | | | ● | |
| HU-05 Avisos de obstáculos | | | | | | | | | | ● | | | | | |
| HU-06 Seguimiento continuo | | | | | | | | | | | | ● | | | |
| HU-09 Saber si hay conexión | ● | | | | | | | | | | | | | | |
| HU-10 Iniciar sesión como admin | | ○ | ● | | | | | | | | | | | | |
| HU-11 Panel con resumen | | | | | | ● | | | | | | | | | |
| HU-13 Recolectar fotos | | ○ | | ○ | | | | | | | | | | | |
| HU-14 Subir un recorrido | | ○ | | ● | ● | | | | | | | | | | |
| HU-15 Gestionar lugares | | | | | | | | ● | | | | | | | |
| HU-16 Gestionar alertas | | | | | | | | | | ● | | | | | |
| HU-17 Revisar imágenes | | | | | | | | | | | ● | | | | |
| HU-18 Gestionar recorridos | | | | | | | | | | | ● | | | | |
| HU-19 Estadísticas | | | | | | | | | | | | | ● | | |
| HU-20 Desplegar automáticamente | ● | | | | | | | | | | | | | | |
| HU-22 Diagnosticar fallos | ● | | | | | | | | | | | | | | ● |
| HU-23 Privacidad de quien se ubica | | | | | | | | | ● | | | | | | |

(Columnas = `BE-1.1` … `BE-6.1`.)
