# PLAN — Backend (`BACKEND_FASTAPI`)

Qué se construye y en qué orden. **Cómo** funciona cada pieza está en [`ARCHITECTURE.md`](./ARCHITECTURE.md);
**por qué y cuándo** cambió algo, en [`CHANGELOG.md`](./CHANGELOG.md); **cómo se comprueba** cada lote, en
[`validation/`](./validation/).

Alineado con `ARCHITECTURE.md` **v0.2.0**.

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
| BE-3.1 | Lugares y alertas | BE-1.3 | BE-1.3 | [`validation-3-1`](./validation/validation-3-1.md) |
| BE-3.2 | Localización | BE-2.4, BE-3.1 | BE-2.2, BE-2.4, BE-3.1, EMB-3.1, EMB-3.2 y un dataset real del campus (FE-2.1) | [`validation-3-2`](./validation/validation-3-2.md) |
| BE-4.1 | Administración de videos e imágenes, y purga | BE-2.2 | BE-2.2, BE-2.4 | [`validation-4-1`](./validation/validation-4-1.md) |
| BE-5.1 | Corrección visual (`/v1/localize/frame`) — diferido | BE-3.2 | — | — |
| BE-5.2 | Eventos de uso y estadísticas — diferido | BE-3.2 | — | — |
| BE-5.3 | Rutas (`/v1/route`) — diferido | BE-3.1 y la decisión abierta 2 del frontend | — | — |
| BE-6.1 | Endurecimiento — diferido | Fases 1–4 cerradas | — | — |

### 2.2 Detalle de cada lote

#### BE-1.1 — Base del servicio
- **Entregables:** estructura de §4.1 en `project/`, `config.py`, middlewares (`X-Request-Id`, logs JSON, errores con
  el formato de §5.1), `GET /v1/health`, `GET /v1/health/ready` (sin base todavía: informa `db` como no configurada),
  `project/Dockerfile`, `project/pyproject.toml` (uv, ruff, pytest, grupo `ops`), `project/docker-compose.yml` para el
  entorno `local`, `src/ops/comun.py`; `.github/workflows/backend.yml` según el contrato de infra §5.9 (sin el paso
  `migrate` hasta BE-1.2).
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
- **Entregables:** `POST /v1/auth/login`, JWT de §5.2, dependencia `requiere_admin`, auditoría de intentos,
  `python -m app.cli crear-usuario` (crea o actualiza y reactiva) y `desactivar-usuario` (§5.9).
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
- **Entregables:** `GET /v1/admin/stats` (§5.5).
- **Criterios de cierre:**
  - C1. Los números coinciden con los datos de prueba creados por el validador.
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

#### BE-3.1 — Lugares y alertas
- **Entregables:** `GET /v1/places`, `GET /v1/alerts` (completo y por diferencias), CRUD de lugares,
  `PUT`/`DELETE` de alertas, `POST /v1/admin/alerts/sincronizar` (§5.3, §5.5); limpieza de *tombstones*.
- **Criterios de cierre:**
  - C1. La secuencia «crear, editar, borrar» de una alerta, sincronizada por diferencias, deja la caché del cliente
    igual a la foto completa.
  - C2. `DELETE` de un id desconocido da 204.
  - C3. Un lugar con el mismo nombre en mayúsculas o con tildes da `409 NOMBRE_DUPLICADO`.
  - C4. Una alerta activa con vigencia futura aparece en la foto completa.
  - C5. `sincronizar` aplica cada cambio por separado y devuelve su resultado.
- **Historias:** HU-05, HU-15, HU-16; habilita HU-03.

#### BE-3.2 — Localización
- **Entregables:** `POST /v1/localize` con el algoritmo de §4.10, `eventos_localizacion`, parámetros calibrados.
- **Calibración:** con el conjunto de EMB-3.2, fijar `LOC_SIM_MIN`, `LOC_SIM_ALTA` y los cortes de nivel, y registrar
  los valores en ARCHITECTURE §5.10 (sube la versión).
- **Criterios de cierre:**
  - C1. En al menos 10 puntos conocidos del campus con dataset, el error mediano es ≤ 15 m.
  - C2. Ninguna respuesta de nivel `alta` tiene error > 30 m.
  - C3. p95 de latencia ≤ 5 s con `embedding` en su tamaño de `dev`.
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

#### BE-5.1 — Corrección visual (diferido)
- **Alcance:** definir en §5.3 el contrato de `POST /v1/localize/frame` (una foto + posición previa), búsqueda
  restringida a un radio. Se desarrolla en paralelo con la fusión PDR + visual de la app (FE-5.1), que lo consume.
- **Historias:** HU-06.

#### BE-5.2 — Eventos de uso y estadísticas (diferido)
- **Alcance:** `POST /v1/eventos` (anónimo) y `GET /v1/admin/stats/uso` para la vista 7.15, incluido el mapa de calor
  de `eventos_localizacion`.
- **Historias:** HU-19.

#### BE-5.3 — Rutas (diferido)
- **Alcance:** modelo del grafo de caminos, cómo se construye (decisión abierta 2 del frontend) y `GET /v1/route`.
- **Historias:** HU-04.

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
| BE-1.1 | 1 | Pendiente | [1-1](./validation/validation-1-1.md) | — | — | Sin código todavía |
| BE-1.2 | 1 | Pendiente | [1-2](./validation/validation-1-2.md) | — | — | |
| BE-1.3 | 1 | Pendiente | [1-3](./validation/validation-1-3.md) | — | — | |
| BE-2.1 | 2 | Pendiente | [2-1](./validation/validation-2-1.md) | — | — | |
| BE-2.2 | 2 | Pendiente | [2-2](./validation/validation-2-2.md) | — | — | |
| BE-2.3 | 2 | Pendiente | [2-3](./validation/validation-2-3.md) | — | — | |
| BE-2.4 | 2 | Pendiente | [2-4](./validation/validation-2-4.md) | — | — | Lo necesita EMB-3.2 |
| BE-3.1 | 3 | Pendiente | [3-1](./validation/validation-3-1.md) | — | — | |
| BE-3.2 | 3 | Pendiente | [3-2](./validation/validation-3-2.md) | — | — | Umbrales de §5.10 provisionales hasta calibrar |
| BE-4.1 | 4 | Pendiente | [4-1](./validation/validation-4-1.md) | — | — | |
| BE-5.1 | 5 | Diferido | — | — | — | |
| BE-5.2 | 5 | Diferido | — | — | — | |
| BE-5.3 | 5 | Diferido | — | — | — | Depende de la decisión abierta 2 |
| BE-6.1 | 6 | Diferido | — | — | — | |

---

## 4. Matriz de trazabilidad

● = el lote entrega la historia (total o parcialmente) · ○ = la habilita (otra carpeta la cierra).

| Historia | 1.1 | 1.2 | 1.3 | 2.1 | 2.2 | 2.3 | 2.4 | 3.1 | 3.2 | 4.1 | 5.1 | 5.2 | 5.3 | 6.1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HU-01 Ubicarme con una vuelta | | | | | ○ | | ○ | | ● | | | | | |
| HU-02 Conocer mi ubicación y referencias | | | | | | | | ○ | ● | | | | | |
| HU-03 Elegir destino | | | | | | | | ○ | | | | | | |
| HU-04 Ser guiada hasta el destino | | | | | | | | | | | | | ● | |
| HU-05 Avisos de obstáculos | | | | | | | | ● | | | | | | |
| HU-06 Seguimiento continuo | | | | | | | | | | | ● | | | |
| HU-09 Saber si hay conexión | ● | | | | | | | | | | | | | |
| HU-10 Iniciar sesión como admin | | ○ | ● | | | | | | | | | | | |
| HU-11 Panel con resumen | | | | | | ● | | | | | | | | |
| HU-13 Recolectar fotos | | ○ | | ○ | | | | | | | | | | |
| HU-14 Subir un recorrido | | ○ | | ● | ● | | | | | | | | | |
| HU-15 Gestionar lugares | | | | | | | | ● | | | | | | |
| HU-16 Gestionar alertas | | | | | | | | ● | | | | | | |
| HU-17 Revisar imágenes | | | | | | | | | | ● | | | | |
| HU-18 Gestionar recorridos | | | | | | | | | | ● | | | | |
| HU-19 Estadísticas | | | | | | | | | | | | ● | | |
| HU-20 Desplegar automáticamente | ● | | | | | | | | | | | | | |
| HU-22 Diagnosticar fallos | ● | | | | | | | | | | | | | ● |
| HU-23 Privacidad de quien se ubica | | | | | | | | | ● | | | | | |

(Columnas = `BE-1.1` … `BE-6.1`.)
