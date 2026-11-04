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

## [0.16.1] — 2026-10-28

- **Lote que la motivó:** BE-5.1 (cierre: `validate51.py --entorno dev` con código 0 sobre `92b9cee`, PLAN §3).
- **Qué cambió:** encabezado y §4.14 (BE-5.1 validado en `dev`, con lo medido y la trampa del despliegue: `/v1/health`
  con el *commit* nuevo mientras una tarea vieja aún responde `501` al frame); PLAN: fila BE-5.1 «Hecho» y «Alineado con
  v0.16.1».
- **Contratos tocados (§5):** ninguno (versión de parche).
- **Cómo se verificó:** `validate51.py --entorno dev` con código 0 sobre `92b9cee` sin `-dirty` (2026-10-28,
  15:20–15:21 UTC, informe `.validacion/BE-5.1-20261028-152156.json`; el maestro, tras el despliegue de `backend.yml`):
  P1–P5, C4, C1, C2, C3, C6 (mediana 262 ms y máxima 420 ms en el servidor) y C5 en verde; limpieza del video
  `validacion-51-` (la purga limpia S3) y `embedding` encendido como estaba (decisión del usuario: todo el día). Pruebas
  con base en el CI del PR 12 («lint y pruebas» en verde).

## [0.16.0] — 2026-10-28

- **Lote que la motivó:** BE-5.1 (Corrección visual, `POST /v1/localize/frame`), construcción; es el lote del backend
  de la meta «Guía en tiempo real (fotos + pasos)» (`PRIORITY-2.md`). Lo consumirá FE-5.3 (guía por voz, vistas
  6.5–6.6). La ejecución en `dev` la coordina el maestro.
- **Qué cambió:**
  - **Contrato primero** (§5.3): `POST /v1/localize/frame` deja de ser reservado. Petición `multipart/form-data` con
    **una** parte `foto` y `metadatos` = `{"rumbo", "posicion_previa": {"lat", "lng"}, "radio_m" (opcional),
    "app_version"}`; respuesta `FrameRespuesta` (lo de `/v1/localize` que aplica con una foto más
    `distancia_previa_m`, `radio_busqueda_m` e `imagenes_en_radio`); `sin_coincidencias` es un `200`; errores `400
    FOTOS_INVALIDAS`/`SOLICITUD_INVALIDA`, `422 VALIDACION`, `503 EMBEDDING_NO_DISPONIBLE`/`BASE_NO_DISPONIBLE`, en el
    orden de `/v1/localize`. «Endpoints reservados» ya no lo lista.
  - **Construido** (§4.14 nueva): búsqueda **exacta** solo entre las imágenes a ≤ `radio_m` (haversine) de la posición
    previa (`db.consultas.buscar_vecinos_en_radio`, CTE materializada sin HNSW, `count(*) OVER ()` para
    `imagenes_en_radio`), el algoritmo de BE-3.2 sin cambios, contexto y fila de `eventos_localizacion` con `origen =
    frame` en una transacción. Código: `esquemas/localizacion.py` (`PARTE_FOTO`, `PosicionPrevia`, `MetadatosFrame`,
    `FrameRespuesta`, `app_version_admitida`), `db/consultas.py`, `servicios/localizar.py` (`localizar_frame` y las
    piezas `_vectorizar`, `_contexto`, `_guardar_evento` que comparte con `localizar`), `api/v1/localizar.py` (la ruta
    y las piezas `_partes`, `_metadatos_validados`, `_errores_del_servicio` y los helpers de salida, compartidos con
    `/v1/localize`), `config.py` (`loc_frame_radio_*`) y `api/v1/reservados.py` (sin la ruta). `/v1/localize` no cambia
    de comportamiento (mismo orden de errores, mismos textos; sus pruebas siguen en verde). Sin migración ni cambios de
    infraestructura.
  - **ADR-BE-21** (filtrar por distancia en la consulta y no sobre los `LOC_TOP_K` globales; búsqueda exacta; radio 40
    m entre 10 y 100; algoritmo y `LOC_*` de BE-3.2 sin cambios; respuesta propia; evento con `origen = frame`) y riesgo
    **R19** (sin índice geográfico). La guía de §4.10 («filtrar los vecinos antes de `localizar`») queda precisada.
  - §4.1, §4.13 (BE-5.1 construido; BE-5.3 no hace falta por ahora: la ruta se calcula en el teléfono, decisión del
    usuario del 2026-10-27 confirmada el 2026-10-28) y encabezado al día.
  - `validate51.py` nuevo (P1–P5; C4, C1, C2, C3, C6, C5) con sus propios datos (`validacion-51-…`, 4 fotos fuera del
    campus en dos puntos a 300 m) y su prueba con un mundo falso; §5.11 con su descripción. `validation-5-1.md` nuevo.
    PLAN: BE-5.1 con entregables y criterios C1–C6, «Para validar» BE-2.2 y BE-4.1 (no la calibración de BE-3.2), fila
    de §3 «En curso»; BE-5.3 anotado como «no hace falta por ahora».
- **Contratos tocados (§5):**
  - §5.3: subsección nueva `POST /v1/localize/frame`; fila de la tabla y «Endpoints reservados».
  - §5.6: `FOTOS_INVALIDAS` y `VALIDACION` (`metadatos.<campo>`) también en `/v1/localize/frame`.
  - §5.7: «`eventos_localizacion`: filas de BE-5.1» (sin cambio de esquema: `origen = frame` ya estaba en el `CHECK`).
  - §5.10: parámetros nuevos `LOC_FRAME_RADIO_M` / `LOC_FRAME_RADIO_MIN_M` / `LOC_FRAME_RADIO_MAX_M` (40 / 10 / 100) y
    evento de log nuevo `frame_calculado`.
- **Cómo se verificó:** en local (WSL), `ruff check` y `ruff format --check` en verde; `pytest` **sin**
  `PRUEBAS_DB_URL`: 833 pasan y 282 se omiten (las `base`); todas las existentes siguen pasando y las nuevas también
  (`tests/api/test_localizar_frame.py`,
  `tests/contrato/test_contrato_localizacion.py` ampliada, `tests/ops/test_validate51.py` con 7 backends defectuosos;
  `tests/api/test_auth.py`: `/v1/localize/frame` ya no da `501`). Las 8 de `tests/base/test_frame_base.py` **sin
  ejecutar**: no hay Docker ni PostgreSQL en la máquina; corren en el CI de `backend.yml` de un PR. La sentencia de la
  búsqueda es la que compila SQLAlchemy con el dialecto asyncpg (impresa). Nada ejecutado en `dev`.
- **Pendiente:** las pruebas con base en el CI; desplegar (push a `main`) y `validate51.py --entorno dev` con código 0
  para cerrar BE-5.1 en PLAN §3. Medir en `dev` la latencia real de un frame (C6 la exige ≤ 1 s) y, con el día de
  campo de FE-5.3, el radio y si el nivel de un frame (más alto que el de un escaneo, ADR-BE-21) necesita cortes
  propios. Frontend: FE-5.3 consume el contrato de §5.3 (parte `foto`, no `fotos`).

## [0.15.1] — 2026-10-27

- **Lote que la motivó:** BE-4.1 (cierre: `validate41.py --entorno dev` con código 0 sobre `c5f6517`, PLAN §3).
- **Qué cambió:**
  - Encabezado y §4.12: BE-4.1 validado en `dev`, con lo visto (tiempos de procesado y purga, similitudes de C1a,
    reconciliador de C3) y dónde corrieron las pruebas con base (CI del PR 11 y de `main`).
  - §5.11: `validate41.py` ejecutado en `dev`. `validation-4-1.md` §5, paso 2: la integración se hizo durante el día de
    campo por decisión del usuario (la regla sigue: no durante una recolección activa). PLAN: fila BE-4.1 «Hecho» y
    «Alineado con v0.15.1».
- **Contratos tocados (§5):** ninguno (versión de parche).
- **Cómo se verificó:** `validate41.py --entorno dev` con código 0 sobre `c5f6517` sin `-dirty` (2026-10-27,
  18:53–19:23 UTC, informe `.validacion/BE-4.1-20261027-192259.json`; ejecutado por el maestro tras el despliegue de
  `backend.yml` run 40562670663): P1–P5, C5b, C4a, C1a, C1b, C4b, C5a, C2 y C3 en verde; limpieza: escalado de
  `worker` sin tocar, `embedding` encendido como estaba. Antes, pasos 3–5 de la guía: `/v1/health` con `c5f6517`,
  `/v1/admin/images` → `401`, `api` y `worker` con la misma imagen, escalado sin suspender, `purga` y su DLQ en 0. El
  rebase sobre `main` no tocó `BACKEND_FASTAPI` (el código es el de `8543dfe`, cuyo CI del PR 11 pasó con base).
- **Pendiente:** nada de BE-4.1. Lo consume FE-4.1 (vistas 7.11–7.14).

## [0.15.0] — 2026-10-26

- **Lote que la motivó:** BE-4.1 (Administración de videos e imágenes, y purga), construcción; la ejecución en `dev`
  la coordina el maestro. Lo consumirán FE-4.1 (vistas 7.11–7.14) y la comparación de variantes de EMB-3.2 (las `url`
  del detalle de un video).
- **Qué cambió:**
  - **Construido** (§4.12 reescrita): `PATCH` y `DELETE /v1/admin/videos/{id}`, `GET /v1/admin/images`,
    `GET`/`PATCH`/`DELETE /v1/admin/images/{id}`, `POST /v1/admin/images/lote`, `POST
    /v1/admin/images/{id}/reprocesar`, URLs prefirmadas GET en `ImagenAdmin` (también en `GET /v1/admin/videos/{id}`),
    la purga de la cola `purga` en el `worker` (`purgar_video`, `purgar_imagen`) y el reconciliador en `api`. Código
    nuevo: `servicios/imagenes.py`, `servicios/purga.py`, `api/v1/admin_imagenes.py`; cambios en `servicios/videos.py`,
    `api/v1/admin_videos.py`, `api/v1/__init__.py`, `api/dependencias.py`, `clientes/s3.py` (`firmar_get`,
    `firmar_gets`), `clientes/sqs.py` (`enviar`, `Colas`, `crear_colas`), `dominio/mensajes.py` (mensajes de `purga` y
    cuerpos que envía `api`), `esquemas/videos.py`, `errores.py`, `main.py` (colas y tarea `reconciliador-purgas`) y
    `worker.py` (el bucle consume también `purga`, en serie con la ingesta; `procesar_lote` de la ingesta no cambia).
    Sin migración ni cambios de infraestructura.
  - **ADR-BE-20** (purga: video tras el `COMMIT` con reconciliador, imagen y re-procesado dentro de la transacción,
    purga en serie con la ingesta, mensajes acotados, `DELETE` de video repetido igual y de imagen `404`, `409` al
    re-procesar una foto sin subir, URLs que no rompen el detalle) y riesgo **R18** (purga pendiente sin `worker`;
    huérfanos de un `purgar_imagen` en la DLQ).
  - §4.1, §4.2, §4.5, §4.9 y §4.11 al día (las guías para BE-4.1 de §4.9 y §4.11, aplicadas). §4.12 incluye «Para la
    app (FE-4.1)».
  - `validate41.py` nuevo (P1–P5; C5b, C4a, C1a, C1b, C4b, C5a, C2, C3) y su prueba con un mundo falso; §5.11 con su
    descripción y la fila de limpieza «con BE-4.1 hecho». `validation-4-1.md` reescrito con su §5 completo.
  - Contradicciones corregidas: `validation-4-1` P3 pedía `embedding` encendido junto con BE-2.2 y P4 una consulta
    `vecinos` (que necesita `embedding`) antes de encenderlo; ahora P5 enciende `embedding` al final, como en
    `validate24.py`. C3b contaba solo `ApproximateNumberOfMessages` (aproximado y con retraso): ahora exige el evento
    `purgas_reencoladas` del log de `api` y el contador queda como evidencia. P5 (objetivo escalable) pasa a P4. La
    preparación borraba con `limpiar-validacion` en el texto de otros validadores; aquí con `DELETE`. §5.5 decía de
    `ImagenAdmin` «hasta BE-4.1 … `null`» y `total_fotos` de lugares «hasta BE-4.1 … es 0».
- **Contratos tocados (§5):**
  - §5.5: `ImagenAdmin` con las reglas de `url`, `url_miniatura` y `url_expira_en`; filas de la tabla precisadas (sin
    cambiar las formas: `DELETE` de imagen repetido → `404`; `reprocesar` → `202` sin cuerpo o `409
    IMAGEN_NO_SUBIDA`); subsecciones nuevas «Videos: `PATCH` y `DELETE` (BE-4.1)» e «Imágenes: `/v1/admin/images`
    (BE-4.1)» con ejemplos, reglas y orden de errores; el detalle de video firma las URLs.
  - §5.6: código nuevo `409 IMAGEN_NO_SUBIDA`; `500 ERROR_INTERNO` también por falta de `SQS_URL_PURGA`/`SQS_URL_INGESTA`
    en `api` y por SQS que no acepta un mensaje en las rutas que encolan dentro de la transacción.
  - §5.7: «`auditoria`: filas de BE-4.1» (`video.renombrar`, `video.eliminar`, `imagen.editar`, `imagen.eliminar`,
    `imagen.reprocesar`), sin cambio de esquema. §5.8: quién envía cada mensaje y cuándo, qué exige el `worker` (en
    `purgar_imagen`, solo las dos claves de la imagen), cuándo descarta y que el reconciliador puede duplicar
    `purgar_video` (formato sin cambios). §5.9: el `worker` consume `purga`. §5.10: notas de `PRESIGN_GET_TTL_S` y
    `RECONCILIADOR_CADA_MIN`; eventos nuevos (`video_renombrado`, `video_eliminado`, `purga_no_encolada`,
    `imagen_editada`, `imagen_eliminada`, `imagen_reprocesada`, `imagenes_lote`, `purgas_reencoladas`,
    `reconciliador_fallido`, `lote_purga`, `video_purgado`, `imagen_purgada`, `purga_descartada`,
    `purga_transitoria`) y campos nuevos en `worker_iniciado` (`purga`), `mensaje_no_reconocido` y `cola_fallida`
    (`cola`; también en `api`), `s3_fallido` (`firmar_get`) y `configuracion_incompleta`.
- **Cómo se verificó:** en local (WSL), `ruff check` y `ruff format --check` en verde; `pytest` **sin**
  `PRUEBAS_DB_URL`: 778 pasan y 274 se omiten (las `base`), entre ellas las nuevas `tests/unit/test_purga.py`,
  `tests/contrato/test_contrato_admin.py` y `tests/ops/test_validate41.py` (camino feliz, 5 backends defectuosos, BE-4.1
  sin desplegar → 2, el escalado suspendido que reanuda la preparación). Las 12 de `tests/base/test_admin_videos_base.py`
  **sin ejecutar**: Docker Desktop no arranca en la máquina (sin PostgreSQL local); corren en el CI de `backend.yml` de
  un PR. El SQL de §4.12 es el que compila SQLAlchemy con el dialecto asyncpg (impreso). Nada ejecutado en `dev`.
- **Pendiente:** las pruebas con base en el CI; integrar en `main` **después** del día de campo del 2026-10-27 (cambia
  el bucle del `worker`); `validate41.py --entorno dev` con código 0 y entonces la fila BE-4.1 de PLAN §3 a «Hecho».
  Del frontend (a decidir con FE-4.1): 7.12 pide «dispositivo» y 7.13 «reprocesar embeddings» y «reintentar subida» de
  un video entero, que §5.5 no tiene (hoy: foto a foto); se decide en FE-4.1. ADR-BE-20 aprobada por el maestro
  (2026-10-26).

## [0.14.1] — 2026-10-26

- **Lote que la motivó:** BE-3.3 (cierre: `validate33.py --entorno dev` con código 0 sobre `4885ad6`, PLAN §3).
- **Qué cambió:**
  - Encabezado y §4.11: BE-3.3 validado en `dev`, con lo visto. `dev` no tenía alertas reales (foto completa con 0);
    C1b comprobó que **`If-Match` pasa por API Gateway** (el segundo `PUT` con `If-Match: 1` dio `409
    CONFLICTO_VERSION`) y que `?desde=…Z` sin codificar también llega; C5 dio `alertas_activas` 2 → 3, y s0 = 2 porque en
    ese momento seguían vivas y activas F (C3) y A2 (el `upsert` válido de C4): A ya estaba borrada por C1c, D por el
    `eliminar` de C4 y B nunca se creó (comprobado leyendo `validate33.py`). En el log de `api`, leído después: 7
    `alerta_guardada` de la ejecución y la primera purga diaria (`alertas_purgadas`, 0 borradas, 45 ms) 60 s después de
    `api_iniciada`, sin `limpieza_fallida`. Las pruebas con base, que 0.14.0 dejaba sin ejecutar, corrieron en el CI
    (PR 10). Lo que sigue sin comprobar en `dev` queda listado en §4.11.
  - §4.11, lo que faltaba para hacer los lotes siguientes leyendo solo docs: «Para la app» dice que las alertas no
    dependen de los videos (sin FK: borrar un video en BE-4.1 no las toca, como pide FRONTEND §2.4) y qué comprobó el
    backend en `dev`; «Guía para BE-4.1» explica cómo copiar el patrón de la purga (tarea de asyncio en el ciclo de vida
    de `main.py`, cancelada antes de cerrar el motor, y sus pruebas) para el reconciliador de purgas.
  - §5.11: `validate33.py` ejecutado en `dev`; trampa nueva (el s0 de C5 incluye F y A2; cada ejecución deja 6
    *tombstones*). `validation-3-3.md` §5: el CI del PR 10 y la primera ejecución en `dev`. PLAN: fila BE-3.3 «Hecho» y
    «Alineado con v0.14.1».
- **Contratos tocados (§5):** ninguno (versión de parche; §5.11 solo describe el validador).
- **Cómo se verificó:** `validate33.py --entorno dev` con código 0 sobre `4885ad6` sin `-dirty` (2026-10-26,
  19:15:35–19:16:02 UTC, informe `.validacion/BE-3.3-20261026-191602.json`; ejecutado por el maestro tras el despliegue
  de `backend.yml` run 40383733721): P1–P4, C1a–C1d, C2, C3, C4 y C5 en verde; limpieza: 4 alertas borradas. CI del PR
  10 (run 40383029250, sobre `89f6a52`): `ruff` limpio y 1003 pruebas con base, ninguna omitida. Log de `api` en `dev`
  leído con `aws logs filter-log-events` (solo lectura). En local, `ruff` y `pytest` sin base en verde. El resto, solo
  documentación.
- **Pendiente:** nada de BE-3.3. Lo consumen FE-3.3 y FE-3.6 (ARCHITECTURE §4.11, «Para la app»).

## [0.14.0] — 2026-10-26

- **Lote que la motivó:** BE-3.3 (Alertas, fuera del núcleo), construcción; la ejecución en `dev` la hace el maestro
  tras el push. Lo consumirán FE-3.3 (editor de alertas) y FE-3.6 (alertas públicas), con los que se revisó el contrato.
- **Qué cambió:**
  - **Alertas construidas** (§4.11 nueva): `GET /v1/alerts` (público: foto completa o diferencias desde `desde`),
    `GET /v1/admin/alerts`, `PUT /v1/admin/alerts/{id}` (crea, reemplaza o restaura una borrada, con `If-Match`
    opcional), `DELETE /v1/admin/alerts/{id}` (*tombstone*) y `POST /v1/admin/alerts/sincronizar` (cambio por cambio),
    con auditoría `alerta.upsert`/`alerta.eliminar` y la purga diaria de *tombstones* en `api` (tarea del ciclo de vida
    de `main.py`: 60 s después de arrancar y cada 24 h). Código: `dominio/alertas.py`, `esquemas/alertas.py`,
    `servicios/alertas.py`, `api/v1/alertas.py`; `errores.py` (mensaje de `CONFLICTO_VERSION`), `api/v1/__init__.py`
    y `main.py`. Sin migración (la tabla `alertas` de `0001` ya tenía todo) ni cambios en `servicios/estadisticas.py`.
  - **ADR-BE-19** con lo que ADR-BE-10 y §5 no fijaban: margen de 60 s en las diferencias, `desde` futuro → foto
    completa, `PUT` que restaura, `If-Match` estricto y solo en `PUT`, sobre estricto de `sincronizar` con cambios
    independientes en transacciones propias, `PUT` sin cambios sin escribir, `null` = valor por defecto, vigencias sin
    fracciones, purga en `api` y `q` sin tildes. Riesgo R17 (sincronización por marca de tiempo).
  - §4.11 incluye «Para la app (FE-3.3 y FE-3.6)»: qué espera el backend (caché por diferencias que puede repetir
    cambios; una sola operación pendiente por id, la última, para que crear y borrar antes de sincronizar no deje
    rastro; `VALIDACION` no se arregla reintentando; `503` se reintenta entero; `sincronizar` sin `If-Match`).
  - Las secciones de §4 se desplazan: BE-4.1 pasa a §4.12 y los diferidos a §4.13 (referencias de §4.2 y del docstring
    de `api/v1/reservados.py` al día). §4.1 al día; §4.9 deja solo un enlace a §4.11; §4.7 marca su guía para BE-3.3
    como aplicada.
  - `validate33.py` nuevo (P1–P4, C1a–C1d, C2–C5; `dev` y `local`) y ayudas de alertas en `comun.py`
    (`RUTA_ALERTAS`, `RUTA_ALERTAS_ADMIN`, `RUTA_SINCRONIZAR`, `CAMPOS_ALERTA`, `CAMPOS_ALERTA_ADMIN`,
    `CAMPOS_FOTO_ALERTAS`, `alertas_validacion`, `borrar_alertas`, `borrar_alertas_restos`); §5.11 con su tabla, la
    descripción del validador, su `ApiFalsa` y sus trampas. `validation-3-3.md` reescrito con su §5 completo.
  - Contradicciones corregidas: `validation-3-3` P4 exigía BE-2.3 «Hecho» también en `local` (el PLAN describe `dev`:
    ahora solo en `dev`, y P4 solo corre si C5 está incluida); pedía esperar 1 s entre cambio y diferencia (con el margen
    no hace falta); C1b no comprobaba el `409` y C2 no comprobaba que no quedara *tombstone*. PLAN §2.2 BE-3.3 decía
    «`PUT`/`DELETE` con `If-Match`», pero §5.5 solo lo pone en `PUT` (aclarado). §4.7, §5.5 y PLAN §2.2 BE-2.3 decían
    «`alertas_activas` = 0 mientras no exista BE-3.3»; §5.11 marcaba la limpieza de alertas «sin implementar»; §5.11
    decía que el validador de BE-3.3 extendería el mundo falso de `validate23.py` (usa su propia `ApiFalsa`).
- **Contratos tocados (§5):**
  - §5.3 `GET /v1/alerts`: deja de estar «sin implementar» (antes, `404`). Se precisa, de forma compatible con la caché
    de la app: con `desde`, «modificadas desde `desde`» = desde `desde` − 60 s (`MARGEN_DESDE_S`, ADR-BE-19: una
    diferencia puede repetir cambios ya aplicados); un `desde` posterior a la hora del servidor da también la foto
    completa; `desde` con zona o `422` (`campo` = `desde`); `generado_en` = hora de la base en UTC sin fracciones;
    orden por `actualizado_en` e `id`; errores `422` y `503`; público (ignora `Authorization`).
  - §5.5: las cuatro rutas de alertas sin «sin implementar»; `PUT` → `201` también al restaurar una borrada y `200`
    sin cambios; `DELETE` → `204` también si ya estaba borrada, sin `If-Match`. `AlertaEntrada` en detalle (`null` =
    valor por defecto, vigencias con zona guardadas sin fracciones, `hasta > desde` sin fracciones, campos de más
    ignorados). Subsección nueva «Alertas: `/v1/admin/alerts` (BE-3.3)»: orden y `q` del panel, `If-Match` (`3` o
    `"3"`; `409` también si no existe, `detalle: null`; `422` con `campo` = `If-Match`), orden de errores, sobre de
    `sincronizar` (1–100; mal formado → `422` sin aplicar nada), resultados en orden, `503` a mitad. Fila y detalle de
    `GET /v1/admin/stats` sin «0 mientras BE-3.3 no exista» (misma forma).
  - §5.6: `CONFLICTO_VERSION` (cuándo; `detalle: null`) y `If-Match` como campo de `VALIDACION`. §5.7: nota de
    `eliminada_en` (purga de BE-3.3) y «`auditoria`: filas de BE-3.3» (sin cambio de esquema). §5.10: nota de
    `ALERTAS_TOMBSTONE_DIAS` y los eventos `alerta_guardada`, `alerta_eliminada`, `alertas_sincronizadas`,
    `alertas_purgadas` y `limpieza_fallida`. §5.11: ayudas y validador de BE-3.3.
- **Cómo se verificó:** en local (WSL), `ruff check` y `ruff format --check` en verde; `pytest` **sin**
  `PRUEBAS_DB_URL`, todas pasan salvo las `base`, que se omiten. Nuevas: `tests/unit/test_alertas.py`,
  `tests/api/test_alertas.py`, `tests/contrato/test_contrato_alertas.py` y `tests/ops/test_validate33.py` (sin base, el
  validador contra `ApiFalsa`: camino feliz en `local` y `dev`, `--solo`, restos, 6 backends defectuosos —cada uno
  falla su comprobación— y BE-3.3 o BE-2.3 sin desplegar → código 2), en verde.
  `tests/base/test_alertas_base.py` (28) y las 3 con base de `test_validate33.py` **sin ejecutar**: Docker Desktop no
  arrancó en la máquina (sin PostgreSQL local); corren en el CI de `backend.yml` de un PR. El SQL de §4.11 es el que
  compila SQLAlchemy con el dialecto asyncpg (impreso). `test_contrato_lugares.py` deja de exigir que no haya rutas de
  alertas. Nada ejecutado en `dev`.
- **Pendiente:** las pruebas con base en el CI; `validate33.py --entorno dev` con código 0 sobre un commit de `main`
  desplegado (lo corre el maestro, `validation-3-3.md` §5), y entonces la fila BE-3.3 de PLAN §3 a «Hecho». Sin
  comprobar en `dev` que API Gateway deja pasar `If-Match` (C1b lo comprueba).

## [0.13.1] — 2026-10-26

- **Lote que la motivó:** BE-2.3 (cierre: `validate23.py --entorno dev` con código 0 sobre `012e0ae`, PLAN §3).
- **Qué cambió:**
  - Encabezado y §4.7: BE-2.3 validado en `dev`, con lo medido (`embedding` encendido en 325 s; las 2 fotos de prueba
    en `procesada` en 4,6 min con el `worker` desde 0; `total_fotos` 0 → 0 con las fotos registradas sin subir → 2;
    `total_lugares` 0 → 2 → 1; `ultimo_video` = el video de prueba; `alertas_activas` = 0). Las pruebas con base, que
    0.13.0 dejaba sin ejecutar porque Docker Desktop no arrancó en la máquina, corrieron en el CI de `backend.yml` del
    PR 9 (run 40374138268: 874 pruebas, ninguna omitida): quitados los «sin ejecutar» de §4.7 y del encabezado.
  - §4.7, lo que faltaba para no abrir `project/`: dos trampas de las pruebas (la de contrato lee §5.5 como texto —qué
    encabezados busca, qué bloque `json` y qué fila exige, y qué del OpenAPI— y la que cuenta 6 `SELECT` en
    `sql_resumen()`); en «Nombres internos», los componentes del OpenAPI (`ResumenPanel`, `UltimoVideo`, etiqueta
    `panel`, sin `parameters`); en la fila «Pruebas con base», la fixture `ajustes_st`, `_resumen(api)`, `RUTA`,
    `VACIO`, `FECHA_UTC` y qué deja `alerta()` en la fila (para el C5 de BE-3.3 con base).
  - §5.11, `validate23.py`: ejecutado en `dev`; `incluida(solo, id_)` y qué decide; el estado del `Contexto` y lo que
    sustituyen las pruebas; el mundo falso de `test_validate23.py` en detalle (valores previos, cómo responde cada ruta,
    `foto_ajena_en_cola`, `_HttpFijo` y `BUENO`) y cómo extenderlo para el validador de alertas.
  - `validation-2-3.md` §5 paso 1: cómo aislar el compose con otro proyecto y otro puerto (sin comprobar) y, si Docker
    no arranca, correr las pruebas con base en el CI de un PR (sin desplegar). PLAN: fila BE-2.3 «Hecho» y «Alineado
    con v0.13.1».
- **Contratos tocados (§5):** ninguno (versión de parche; §5.11 solo describe el validador).
- **Cómo se verificó:** `validate23.py --entorno dev` con código 0 sobre `012e0ae` sin `-dirty` (2026-10-26, 18:22–18:26
  UTC, informe `.validacion/BE-2.3-20261026-182628.json`; ejecutado por el maestro tras el despliegue de `backend.yml`
  run 40374740872): P1–P5 y C1a, C1b, C1c en verde; limpieza: `embedding` apagado (lo encendió el validador), video
  borrado (`{"videos": 1, "objetos": 4}`) y lugar borrado. CI del PR 9 (run 40374138268): `ruff` limpio y 874 pruebas
  con base, ninguna omitida. El resto, solo documentación.
- **Pendiente:** nada de BE-2.3. `alertas_activas` con datos: C5 de BE-3.3.

## [0.13.0] — 2026-10-26

- **Lote que la motivó:** BE-2.3 (Resumen del panel), construcción; la ejecución en `dev` la hace el maestro tras el
  push. Lo consume FE-2.2 (panel de la app), que se construye en paralelo contra §5.5.
- **Qué cambió:**
  - **`GET /v1/admin/stats` construido** (§4.7 reescrita): router `api/v1/admin_estadisticas.py` (en `RUTAS_ADMIN`),
    `servicios/estadisticas.py` (**una** sentencia con cinco subconsultas escalares en una transacción corta: las cifras
    salen de la misma instantánea) y `esquemas/estadisticas.py` (`ResumenPanel`, `UltimoVideo`). Sin migración, sin
    evento de log propio y sin auditoría. `GET /v1/admin/stats/uso` (BE-5.2) sigue respondiendo `501`.
  - §4.7 con el SQL, qué cuenta cada cifra, nombres internos, «qué ofrece BE-2.3 al código», una guía para BE-3.3
    (`alertas_activas` ya cuenta bien si BE-3.3 escribe `alertas` como dice §5.7; su C5 con `comun.resumen_panel`) y
    trampas. §4.1 al día.
  - Ayudas nuevas en `comun.py` (`RUTA_STATS`, `CAMPOS_RESUMEN`, `CAMPOS_ULTIMO_VIDEO`, `PATRON_FECHA_UTC`,
    `resumen_panel`) y `validate23.py` nuevo (P1–P5, C1a–C1c); §5.11 con su tabla, la descripción del validador, su
    mundo falso y sus trampas. `validation-2-3.md` reescrito con su §5 completo (Variables, Preparación y Ejecución).
  - Contradicciones corregidas en `validation-2-3.md`: P2 comprobaba BE-2.1 (con un `POST …/images` a un video
    inexistente), pero PLAN §2.1 pide para validar BE-2.2 y BE-3.1 (BE-2.1 ya lo implica BE-2.2); la hora límite era
    21:30, con un encendido de hasta 10 min y un procesado de hasta 20 min (ahora 21:00, como BE-2.4 y BE-3.2, y solo
    si C1a está incluida); P3 juntaba BE-2.2 y el encendido de `embedding`, que cambia algo, antes de comprobar el resto
    (ahora el encendido es P5, la última); C1a leía s1 «tras C1b», así que C1a dependía de C1b (ahora cada
    comprobación lee sus cifras antes y después de crear sus datos); la limpieza no decía qué hacer con `embedding`;
    §5 no tenía Preparación ni la salida esperada.
- **Contratos tocados (§5):** §5.5 `GET /v1/admin/stats`: subsección nueva con el ejemplo y el detalle, **sin cambiar
  la forma** de la respuesta de la fila de la tabla (los mismos cuatro campos y tipos). Se fija lo que la fila no
  decía: «último video» = el no eliminado con el `creado_en` más reciente y, a igualdad, `numero` mayor (el primero de
  `GET /v1/admin/videos` por defecto), cualquier video aunque no tenga fotos, `null` sin videos; `creado_en` del
  registro en el backend, en UTC con `Z` y sin fracciones; `alertas_activas` sin mirar la vigencia; las cifras de la
  misma instantánea; errores (los de §5.2 y `503 BASE_NO_DISPONIBLE`); parámetros de la URL ignorados. §5.11: ayudas y
  validador de BE-2.3.
- **Cómo se verificó:** en local (WSL), `ruff check` y `ruff format --check` en verde; `pytest` **sin**
  `PRUEBAS_DB_URL`: 643 pasan y 231 se omiten (todas las `base`). Docker Desktop no arrancó en la máquina (se cerraba
  con un error sobre un socket viejo en `%LOCALAPPDATA%\Docker\run`), así que no hubo PostgreSQL local: las pruebas con
  base, también las 11 nuevas, **quedan sin ejecutar** (paso 1 de `validation-2-3.md` §5). Nuevas:
  `tests/base/test_estadisticas_base.py` (base vacía → ceros y `null`; solo `procesada` de videos no eliminados; todos
  los lugares, también al crear y borrar por la API; alertas activas sin borrar y sin mirar la vigencia; último video
  por `creado_en` con desempate por `numero` y sin los eliminados; coherencia con `POST /v1/collect/videos` y con el
  primero de `GET /v1/admin/videos`; parámetros ignorados, `401`, `403` con un token `user`, `/stats/` → `404` y
  `/stats/uso` → `501`), `tests/contrato/test_contrato_estadisticas.py` (el ejemplo y la fila de §5.5 contra
  `ResumenPanel` y el OpenAPI) y `tests/ops/test_validate23.py` (mundo falso con interruptores, cola de `ingesta` con
  una foto ajena, `--solo`, horario, restos y `comun.resumen_panel`), estas dos en verde. El SQL de §4.7 es el que
  compila SQLAlchemy con el dialecto de PostgreSQL. Nada ejecutado en `dev`.
- **Pendiente:** las pruebas con base (las nuevas y las de siempre) contra el `db` del compose;
  `validate23.py --entorno dev` con código 0 sobre un commit de `main` desplegado (lo corre el maestro,
  `validation-2-3.md` §5), y entonces la fila BE-2.3 de PLAN §3 a «Hecho».

## [0.12.1] — 2026-10-26

- **Lote que la motivó:** BE-3.2 (sigue «En curso»), y FE-3.2, que consume `POST /v1/localize`.
- **Qué cambió:**
  - **ADR-BE-18 confirmado por el usuario (2026-10-26):** centroide de grupo = media sin ponderar y margen `m = (p₁ −
    p₂) / p₁` dejan de ser «a confirmar» en §4.10 (pasos 4 y 7), en ADR-BE-18 y en la fila BE-3.2 de PLAN §3. La
    simulación de EMB-3.2 usa lo mismo (`SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §4.5).
  - **Aclaración de `referencias` con `lugar_cercano` nulo** (§4.10 paso 9, §5.3 y ADR-BE-18): «los siguientes» se
    leía como si siempre se saltara el primero. El código (`dominio.localizacion.contexto`) solo quita el objeto
    `cercano`: si no hay lugar cercano (el más cercano está a más de `LOC_LUGAR_CERCANO_M`), ese más cercano es la
    primera referencia cuando está a ≤ `LOC_REFERENCIAS_M`. Lo preguntó el lote FE-3.2.
  - PLAN: alineado con 0.12.1.
- **Contratos tocados (§5):** §5.3, aclaración de `referencias` sin cambio de comportamiento.
- **Cómo se verificó:** lectura de `contexto` en `src/app/dominio/localizacion.py` (maestro). Sin cambios de código.
- **Pendiente:** lo mismo que 0.12.0 (dataset real, conjunto e informe de EMB-3.2, calibración y `validate32.py
  --entorno dev`).

## [0.12.0] — 2026-10-25

- **Lote que la motivó:** BE-3.2 (Localización), construcción sin validar: la validación necesita el dataset real
  (FE-2.1), el conjunto de EMB-3.2 y la calibración.
- **Qué cambió:**
  - **`POST /v1/localize` construido** (§4.10 reescrita): router `api/v1/localizar.py` (público, en `router_v1`),
    `servicios/localizar.py` (una llamada a embeddings con prioridad `alta` y tope de 20 s, comparación de
    `version_vector`, y búsqueda + algoritmo + lugares + evento en **una** transacción), `dominio/localizacion.py` (el
    algoritmo en Python puro) y `esquemas/localizacion.py` (`MetadatosLocalizacion` y la respuesta). Reutiliza lo que
    dejaron BE-2.4 (`leer_cuerpo`, `partes_multipart`, `motivo_foto_no_valida`, `buscar_vecinos`, `TOPE_EMBEDDING_S`,
    `VersionVectorDistinta`, la traducción de errores y eventos de embeddings) y BE-3.1 (`lugares.leer_todos`,
    `geo.distancia_m`, `geo.rumbo_grados`, `DECIMALES_DISTANCIA`). Sin alertas en la respuesta (BE-3.3).
  - **ADR-BE-18** con los detalles que §4.10 no fijaba: centroide de grupo = **media sin ponderar** de sus miembros,
    recalculada al añadir cada uno, y margen **`m = (p₁ − p₂) / p₁`** (1 con un solo grupo) —decisión del maestro con
    autorización del usuario (2026-10-25), **a confirmar por el usuario**; es lo que ya simula la herramienta de
    calibración de EMB-3.2—; desempates (orden de llegada, grupo creado antes, orden de `leer_todos`); radio =
    desviación ponderada con mínimo; corrección de rumbo con la mejor coincidencia con rumbo de cada foto y desviación
    estándar circular; confianza **truncada** a 2 decimales con el nivel decidido sobre ese valor; `referencias` sin el
    lugar cercano; evento solo con `200`. ADR-BE-08 enlaza a ADR-BE-18.
  - Parámetros `LOC_*` de §5.10 **sin cambiar** (siguen «Iniciales»): §4.10 «Calibración» dice dónde se cambian
    (`config.py`, §5.10, CHANGELOG y la copia de `metricas.py` de EMB-3.2) y C6 falla hasta entonces.
  - `validate32.py` nuevo (P1–P6, C1–C6), sin ayudas nuevas en `comun.py`; §5.11 con su descripción, el mundo falso de
    sus pruebas y sus trampas. `validation-3-2.md` reescrito: precondiciones con el contrato común (lo que falta en la
    máquina o la hora dan 3, otro lote sin terminar da 2; antes decía «código 2» para todas), BE-2.4 añadido a P2, P3
    comprueba que BE-3.2 está desplegado, el encendido de `embedding` pasa a P6 (la última, la única que cambia algo),
    orden de ejecución C1, C3, C5, C2, C4a, C4b, C4c, C6, el conjunto se descarga en memoria (no en `.validacion/`),
    C6 con la versión 0.12.0 (decía «mayor que 0.2.0») y §5 completo.
  - §4.1, §4.8 y §4.9 (sus guías para BE-3.2, aplicadas), R1 y R2 al día; §5.11, el *Session Manager plugin* para C4c.
  - Contradicciones corregidas: `validation-3-2.md` decía que toda precondición fallida daba código 2 (las
    credenciales, las herramientas y la hora dan 3, infra §5.11); su P2 no pedía BE-2.4, que PLAN §2.1 sí exige para
    validar; su P3 encendía `embedding` antes de comprobar el resto; C2 revisaba respuestas de C3, que se ejecutaba
    después; C6 pedía una versión «mayor que 0.2.0», que ya se cumplía; la hora límite era 21:30 con un encendido de
    hasta 10 min (ahora 21:00, como BE-2.4); C1 y P5 usaban consultas SQL distintas para el dataset (ahora una sola,
    `SQL_DATASET`, con vector de la versión activa y sin videos `validacion-`). §4.9 decía que P2 pedía `GET
    /v1/places` con `total` ≥ 1, algo que no garantiza ningún lote: ahora basta `200`.
- **Contratos tocados (§5):** §5.3 `POST /v1/localize` detallado sin cambiar lo que ya decía: reglas de las partes
  (orden de llegada, tipo, tamaño, firma, tope del cuerpo, partes ignoradas), `metadatos` (obligatorios `rumbos` y
  `origen`, `app_version` opcional ≤ 40, ≤ 16 384 bytes, campos de más ignorados), decimales de la respuesta,
  `confianza` truncada, rango de `correccion_rumbo_grados` (−180, 180], qué son `fotos_con_coincidencia` y
  `latencia_ms`, `referencias` sin el cercano y su orden, y errores en orden: `detalle.motivo` en `400
  FOTOS_INVALIDAS` (campo adicional), `422 VALIDACION` y `400 SOLICITUD_INVALIDA` para `metadatos` (casos que no
  estaban definidos), `400 FOTOS_INVALIDAS` si embeddings no puede decodificar una foto, `503` con otra
  `version_vector` o sin respuesta en 20 s en total. §5.6 (`FOTOS_INVALIDAS` con `motivo` también en `localize`;
  `VALIDACION` de `metadatos`). §5.7: «filas de BE-3.2» de `eventos_localizacion` (sin cambio de esquema). §5.10:
  notas de los `LOC_*` y evento nuevo `localizacion_calculada`; `embedding_no_disponible` y `version_vector_distinta`
  también en `localize`.
- **Cómo se verificó:** en local (WSL), `ruff check`, `ruff format --check` y `pytest` con `PRUEBAS_DB_URL` y
  `PRUEBAS_DB_OBLIGATORIA=1` sobre el `db` del compose (PostgreSQL 17.11, pgvector 0.8.7): 834 pruebas, todas pasan,
  ninguna omitida. Nuevas: `tests/unit/test_localizacion.py` (filtro, centroide sin ponderar recalculado, primer grupo,
  radio estricto, puntuación, desempate, margen, posición y radio ponderados, truncado, cortes, corrección de rumbo y
  contexto), `tests/base/test_localizacion_base.py` (el endpoint con vectores elegidos a mano: `ok` con contexto y su
  fila en `eventos_localizacion`, `sin_coincidencias`, el grupo que reúne varias fotos gana, público, orden de las
  partes, cada `400`/`422`, errores de embeddings sin fila, tope de 20 s y nada de la foto en los logs),
  `tests/contrato/test_contrato_localizacion.py` y `tests/ops/test_validate32.py` (mundo falso con interruptores).
  Nada ejecutado en `dev`.
- **Pendiente:** el dataset real (FE-2.1), el conjunto y el informe de EMB-3.2, la calibración (C6 y una versión
  menor posterior) y `validate32.py --entorno dev` con código 0 sobre un commit de `main` desplegado. Confirmar con el
  usuario las dos decisiones provisionales de ADR-BE-18 (centroide y margen). Sin comprobar hasta la primera
  ejecución en `dev`: C4c con ECS Exec desde un proceso sin terminal y los archivos que deja el agente
  (`EXCLUIDOS_C4C`), el plan de la consulta con el dataset real (R16) y la latencia (C3). `PLAN.md`: fila BE-3.2
  «En curso» y «Alineado con v0.12.0».

## [0.11.1] — 2026-10-25

- **Lote que la motivó:** BE-3.1 (cierre: `validate31.py --entorno dev` con código 0 sobre `86fc024`, PLAN §3), antes
  de empezar BE-3.2.
- **Qué cambió:** encabezado y §4.9 con la validación en `dev`. §4.9, «Guía para BE-3.2», con lo que faltaba para
  hacerlo solo con docs: los importes (`app.servicios.lugares`, `app.dominio.geo`), qué trae `leer_todos` y qué no,
  el redondeo coherente con `GET /v1/places` (`DECIMALES_DISTANCIA`) y el cuidado con un `rumbo_grados` redondeado a
  360, cómo reutilizar en pruebas los ayudantes de `tests/base/test_lugares_base.py` (son de un módulo de pruebas:
  `importlib`, la API o una receta SQL con `nombre_normalizado`) y cómo crea y borra lugares de prueba el validador de
  BE-3.2 con las ayudas de `comun.py`.
- **Contratos tocados (§5):** ninguno (versión de parche).
- **Cómo se verificó:** solo documentación.
- **Pendiente:** nada de BE-3.1.

## [0.11.0] — 2026-10-25

- **Lote que la motivó:** BE-3.1 (Lugares), y la decisión del usuario del 2026-10-25 «no necesitamos las alertas por
  el momento» (resuelve la decisión 1 de §6 de `PRIORITY.md`).
- **Qué cambió:**
  - **Alcance:** BE-3.1 queda solo con lugares. Las alertas pasan a un lote nuevo, **BE-3.3 — Alertas** (fuera del
    núcleo, `Pendiente`, sin código), con los criterios de alertas que tenía BE-3.1 (C1, C2, C4 y C5 de antes, ahora
    C1–C4) y el de `alertas_activas` que tenía BE-2.3 (ahora BE-3.3 C5); `validation/validation-3-3.md` nuevo (borrador,
    sin `validate33.py`). BE-2.3 C1 ya no comprueba `alertas_activas` (su «para validar» sigue siendo BE-2.2 y BE-3.1);
    `validation-2-3.md` sin alertas (el C1c de alertas se va; el antiguo C1d pasa a C1c). BE-3.2 no cambia: la
    respuesta de `POST /v1/localize` (§5.3) no tiene alertas. PLAN: §2.1, §2.2 (BE-2.3, BE-3.1 con criterios C1–C4
    nuevos, BE-3.3), §3 (BE-3.1 «En curso», fila BE-3.3) y §4 (columna 3.3: HU-05 y HU-16 pasan de 3.1 a 3.3).
  - **Lugares construidos** (§4.9 reescrita; ADR-BE-17): `GET /v1/places` y `GET`/`POST /v1/admin/places`,
    `PUT`/`DELETE /v1/admin/places/{id}` (`api/v1/lugares.py`, `servicios/lugares.py`, `esquemas/lugares.py`,
    `dominio/lugares.py` con `normalizar_nombre` y `dominio/geo.py` con `distancia_m` y `rumbo_grados`). Nombre único
    por `nombre_normalizado` (NFKD sin marcas, `casefold`, espacios reducidos); crear con `ON CONFLICT DO NOTHING`;
    `PUT` sin cambios no escribe; `DELETE` con orden de bloqueo videos → lugar → fotos y `204` también si no existe;
    distancia (haversine) y orden en Python; auditoría `lugar.*`; eventos `lugar_guardado` y `lugar_eliminado`. Sin
    migración (la tabla existe desde `0001`). `MENSAJE_POR_CODIGO["NOMBRE_DUPLICADO"]`.
  - §4.9 deja el diseño de las alertas para BE-3.3 y añade «qué ofrece BE-3.1 al código», guías para BE-3.2
    (`leer_todos`, `geo`) y BE-4.1 (bloqueos y FK) y trampas. §4.1, §4.5, §4.6 y §4.7 al día.
  - `validate31.py` (C1a–C4b, `dev` y `local`), ayudas nuevas en `comun.py` (`RUTA_LUGARES`, `RUTA_LUGARES_ADMIN`,
    `CAMPOS_LUGAR_PUBLICO`, `CAMPOS_LUGAR_ADMIN`, `normalizar_nombre`, `lugares_validacion`, `borrar_lugares`,
    `borrar_lugares_restos`) y §5.11 con su tabla, el ejemplo de `validate31.py` y sus trampas.
    `validation-3-1.md` reescrito solo con lugares y su §5 completo (Variables, Preparación y Ejecución en `dev`, y
    cómo correrlo en `local` contra el compose).
  - Contradicciones corregidas: §4.5 y §4.6 decían que BE-3.1 firmaría y subiría la foto del lugar (`firmar_get`,
    `escribir` en `lugares/{id}.jpg`), pero ni PLAN §2.2 ni §5.5 tenían un endpoint para subirla: queda fuera de
    BE-3.1 y sin lote (`imagen_url` siempre `null`, §5.3). §5.10 decía «limpieza diaria desde `api`» de *tombstones* y
    eventos sin que exista código: ahora lo dice («sin código todavía»). El `validation-3-1.md` anterior comprobaba la
    API con `GET /v1/health` y los lugares necesitan la base: P2 usa `/v1/health/ready` con `"db": "ok"`.
- **Contratos tocados (§5):** §5.3 `GET /v1/places` detallado sin cambiar lo que ya decía (rangos de `lat`/`lng`,
  qué es «por nombre», fórmula y redondeo de `distancia_m`, `422` con el campo que falta, público aunque llegue un
  token no válido; `imagen_url` hoy siempre `null`); `GET /v1/alerts` marcado «sin implementar (BE-3.3)» (hoy `404`).
  §5.5: `LugarEntrada` en detalle (recortes, `alias` `null` = `[]`, regla de «sin mayúsculas ni tildes», `409` con
  `detalle: null`), subsección nueva «Lugares: `/v1/admin/places`» con ejemplos de `LugarEntrada` y `LugarAdmin`, orden
  de errores, `PUT` que reemplaza todo (lo que no se envía vuelve a su valor por defecto), `DELETE` de un id
  desconocido = `204` (caso que no estaba definido), `q` sin tildes ni mayúsculas y `total_fotos`; rutas, objetos y
  `AlertaEntrada` de alertas marcados «sin implementar (BE-3.3)»; `alertas_activas` de `GET /v1/admin/stats` = 0 hasta
  BE-3.3. §5.6 (`NOMBRE_DUPLICADO` al crear o editar; `CONFLICTO_VERSION` es de BE-3.3). §5.7: filas de `auditoria` de
  BE-3.1 (sin cambio de esquema). §5.10: eventos `lugar_guardado` y `lugar_eliminado`. §5.11: ayudas de BE-3.1.
- **Cómo se verificó:** en local (WSL), `ruff check`, `ruff format --check` y `pytest` con `PRUEBAS_DB_URL` y
  `PRUEBAS_DB_OBLIGATORIA=1` sobre el `db` del compose (PostgreSQL 17.11, pgvector 0.8.7): 719 pruebas, todas pasan.
  Nuevas: `tests/base/test_lugares_base.py`, `tests/unit/test_lugares.py`, `tests/contrato/test_contrato_lugares.py` y
  `tests/ops/test_validate31.py` (el validador contra la app real con base efímera, en `local` y en `dev` con AWS
  simulado, y con backends defectuosos). `validate31.py --entorno local` contra el compose (`api` construida con este
  código): código 0, las once comprobaciones `[PASA]`.
- **Pendiente:** `validate31.py --entorno dev` sobre un commit de `main` desplegado (lo corre el maestro;
  `validation-3-1.md` §5). Foto del lugar (endpoint de subida y `firmar_get`; infra §5.5 reserva `lugares/` para la
  Fase 4) sin lote en PLAN. BE-3.3 entero. Docs de otras carpetas que nombran las alertas de BE-3.1 (`README.md`
  raíz, fase 3; los ajusta el maestro).

## [0.10.1] — 2026-10-25

- **Lote que la motivó:** BE-2.4 (cierre: `validate24.py --entorno dev` con código 0 sobre `50d931d`, PLAN §3).
- **Qué cambió:**
  - Encabezado y §4.8: BE-2.4 validado en `dev`, con lo medido (similitud de cada foto de prueba consigo misma 0,9991,
    0,9992 y 0,9996 tras la copia reducida del `worker`; el multipart binario y un cuerpo de 1,6 MiB pasan por API
    Gateway hasta el backend; índice con N = 3, así que el plan con un dataset real sigue a verificar, R16).
  - §4.8: «Guía para BE-3.2» (cuerpo, partes `fotos` y `metadatos`, una llamada a embeddings con prioridad `alta` y la
    misma traducción de errores y eventos, `buscar_vecinos` con todas las fotos en una transacción y el filtro
    `LOC_SIM_MIN` después, valores crudos de `Vecino`, la fila de `eventos_localizacion`, dobles de prueba) y dos
    trampas (un vector de otra dimensión que 384 sale como `500`; el nombre de archivo de la parte no se mira).
  - §5.11: cómo reutilizar C4a y C4b de `validate24.py` en la comprobación de privacidad de BE-3.2, y lo medido en
    `dev` (encendido de `embedding` en 311 s, fotos en `procesada` en 4,1 min).
- **Contratos tocados (§5):** ninguno (versión de parche).
- **Cómo se verificó:** solo documentación; las pruebas de contrato que leen este documento (`tests/contrato/`)
  siguen pasando.
- **Pendiente:** `EXPLAIN` de la consulta de vecinos en `dev` con un dataset real (R16). `PLAN.md` dice «Alineado con
  v0.10.0»: lo actualiza el maestro (no se tocó el PLAN en este cambio).

## [0.10.0] — 2026-10-25

- **Lote que la motivó:** BE-2.4 (Diagnóstico de búsqueda).
- **Qué cambió:**
  - `POST /v1/admin/diagnostico/vecinos` construido (router `api/v1/admin_diagnostico.py` en `RUTAS_ADMIN`): cuerpo
    leído en memoria con tope (`api/cuerpo.py`), multipart partido a mano (`dominio/multipart.py`), reglas de la foto
    (`dominio/fotos.py`), vectorización con prioridad `baja` y tope total de 20 s, comparación de `version_vector` con
    cada respuesta, búsqueda en una transacción corta (`servicios/diagnostico.py`).
  - La consulta de vecinos del proyecto, escrita una vez para BE-2.4 y BE-3.2: `db/consultas.py`
    (`buscar_vecinos(conexion, vectores, *, k, version_vector, ef_search)` → una lista de `Vecino` por vector; versión
    como literal, `ef_search = max(LOC_EF_SEARCH, k)` con `set_config(…, true)`, unión con `imagenes` fuera de la
    subconsulta ordenada).
  - §4.8 reescrita con lo construido: orden de las respuestas, la consulta, el plan de PostgreSQL (trampa: con pocas
    filas puede no usar el índice HNSW), por qué no `request.form()`, la tabla «qué ofrece BE-2.4 al código» para
    BE-3.2 y BE-4.1, y trampas. §4.1 con los módulos nuevos. §4.6: `ImagenRechazada` ya tiene respuesta en `api` y el
    doble de embeddings «la misma foto, el mismo vector» existe (`vector_de`).
  - ADR-BE-16 (foto en memoria, una sola consulta de vecinos, errores de embeddings). R16 nuevo (HNSW aproximado y plan
    sin el índice con pocas filas).
  - §5.11: ayudas de `comun.py` para BE-2.4 (`lote_hecho`, que sube desde `validate22.py`, `pedir_vecinos`,
    `jpeg_patron`, `jpeg_ruido`, `png_sintetico`, `jpeg_relleno`, `mensajes_log`, `RUTA_VECINOS`, `LOG_API`,
    `LOG_EMBEDDING`), `validate24.py` como ejemplo (`RecorridoPatrones`, `incluida`, `SQL_CONTEOS`, `Contexto`) y su
    mundo falso. `validate22.py` importa `lote_hecho` de `comun.py` (sin cambio de comportamiento).
  - `validation/validation-2-4.md` reescrito: precondiciones reordenadas (el encendido de `embedding`, P5, va la
    última), C1 hasta 20 min, N de C2 por SQL, §4 con el encendido y la limpieza y §5 completo.
  - PLAN: alineado con 0.10.0; fila BE-2.4 «En curso».
  - Contradicciones corregidas: `validation-2-4.md` C1 esperaba `version_vector = dinov2-vitb14/pp-v1`, pero la
    versión activa es `dinov2-vits14/pp-v1` (§5.10, embeddings §5.3); C2a leía N de `GET /v1/admin/stats`, que es de
    BE-2.3 (Pendiente, y no es dependencia de BE-2.4 en PLAN §2.1): ahora lo cuenta con SQL; esperaba `procesada` en
    10 min y empezaba hasta las 21:30, pero la subida de `worker` puede tardar hasta 15 min (lo vio BE-2.2): 20 min y
    21:00; P2 encendía `embedding` antes de comprobar el login y los recursos (ahora P5) y P4 no comprobaba INF-2.1,
    que el encendido necesita. El encabezado de este documento decía «BE-2.2 sin validar en `dev`» y §4.6 «sin
    comprobar en `dev`», pero BE-2.2 está «Hecho» (`3b01b68`).
- **Contratos tocados (§5):** §5.5 `POST /v1/admin/diagnostico/vecinos` detallado sin cambiar nada de lo que ya decía:
  reglas de la parte `foto` (tipo, vacía, tamaño, firma `FF D8 FF`; otras partes ignoradas), orden de los errores,
  `detalle.motivo` nuevo en `400 FOTOS_INVALIDAS` (campo adicional), `indice = 1` con dos partes `foto` (caso que no
  estaba definido), `400 SOLICITUD_INVALIDA` con multipart mal formado, `400 FOTOS_INVALIDAS` si embeddings no puede
  decodificar la foto, `503` si devuelve otra `version_vector`, `similitud` con 6 decimales y qué mide `latencia_ms`.
  §5.6 (`FOTOS_INVALIDAS` con `detalle.motivo`). §5.10: eventos nuevos `vecinos_consultados` y
  `embedding_no_disponible` (`api`), `version_vector_distinta` también en `api`; notas de `EMBEDDING_VERSION_VECTOR`,
  `LOC_MAX_BYTES_FOTO` y `LOC_EF_SEARCH`. Sin cambio de esquema.
- **Cómo se verificó:** en local (WSL), `ruff check`, `ruff format --check` y `pytest` con `PRUEBAS_DB_URL` y
  `PRUEBAS_DB_OBLIGATORIA=1` (todas pasan). Nuevas: `tests/base/test_diagnostico_base.py` (PostgreSQL 17.11 con
  pgvector 0.8.7 y embeddings simulado: la misma foto primera con similitud 1, `k` y orden, índice vacío, solo la
  versión activa, 422, 400 por cada parte que no vale, 401/403, errores de embeddings, nada escrito ni la foto en los
  logs, el plan con el índice parcial y `ef_search` solo en la transacción), `tests/unit/test_multipart.py`,
  `tests/contrato/test_contrato_diagnostico.py`, `tests/ops/test_comun_diagnostico.py` y `tests/ops/test_validate24.py`
  (mundo falso con interruptores de backend defectuoso).
- **Pendiente:** `validate24.py --entorno dev` sobre un commit de `main` desplegado (lo corre el maestro;
  `validation-2-4.md` §5). Sin comprobar en `dev`: el plan de la consulta con un dataset real (R16), la latencia del
  endpoint y la similitud real de una foto consigo misma tras la copia reducida del `worker` (se espera ≥ 0,95).

## [0.9.2] — 2026-10-25

- **Lote que la motivó:** BE-2.2 (segunda ejecución de `validate22.py` en `dev`, sobre `54fdf18`).
- **Qué cambió:**
  - P6 terminó con código 2 («embedding no quedó sano en 10 min: servicediscovery get-instances-health-status:
    InstanceNotFound (aún no)») aunque ECS tenía la tarea `HEALTHY` desde las 18:59:34 y el servicio estable a las
    19:01:00 (Bogotá). Causa (lecturas del maestro): el servicio de Cloud Map de `embedding` (`srv-josm7lql7ddxgzm6`) no
    tiene `HealthCheckConfig` ni `HealthCheckCustomConfig`, y entonces `get-instances-health-status` responde siempre
    `InstanceNotFound`: 0.9.1 lo tomó por «todavía no», pero nunca iba a cambiar. La limpieza apagó `embedding` bien.
  - `comun.EmbeddingDev._sano_en_ecs` ya no usa `get-instances-health-status`: «instancia en Cloud Map» =
    `servicediscovery list-instances` con una instancia cuya `AWS_INSTANCE_IPV4` es la IP privada de una tarea
    `HEALTHY` (nueva `comun.ips_privadas(tarea)`, del ENI de `describe-tasks`); sin IP en la tarea, basta ≥ 1
    instancia. Lista vacía o solo otras IP → se sigue esperando. `_sondear` se mantiene para el *throttling*.
  - §5.11: la trampa del arranque reescrita con lo visto en `dev` (Cloud Map sin configuración de salud), la tabla de
    `EmbeddingDev` (llamada y permiso `servicediscovery:ListInstances`) y el doble `CloudMap` de las pruebas.
    `validation-2-2.md` §4 (paso 5 del encendido) y §5 (permiso) al día.
  - Hueco de documentación en otra carpeta (no cambiado aquí; lo reporta el maestro): infra §5.10, paso 5 del contrato
    de encendido, dice «instancia sana en Cloud Map» sin decir con qué llamada, y en este servicio no hay estado de
    salud que consultar.
- **Contratos tocados (§5):** ninguno (solo el validador y su documentación; versión de parche).
- **Cómo se verificó:** `tests/ops/test_validate22.py` con un Cloud Map falso como el de `dev`
  (`get-instances-health-status` siempre `InstanceNotFound`; `list-instances` vacía las 3 primeras veces y después con
  la instancia): P6 pasa; con una instancia de otra IP, código 2; sin permiso, código 3; en los dos fallos la limpieza
  apaga `embedding`. `ruff check`, `ruff format --check` y la suite completa con `PRUEBAS_DB_OBLIGATORIA=1`.
- **Pendiente:** repetir `validate22.py --entorno dev` (el maestro, `validation-2-2.md` §5).

## [0.9.1] — 2026-10-25

- **Lote que la motivó:** BE-2.2 (primera ejecución de `validate22.py` en `dev`, sobre `c5917bd`).
- **Qué cambió:**
  - `validate22.py --entorno dev` terminó con código 3 en P6: mientras la tarea de `embedding` arrancaba, ECS ya daba
    el despliegue por `COMPLETED` con la tarea `HEALTHY`, pero Cloud Map aún no la tenía registrada y
    `servicediscovery get-instances-health-status` respondió **error** `InstanceNotFound` (no una lista vacía), que
    `EmbeddingDev` dejaba pasar sin traducir («error inesperado»). La limpieza apagó `embedding` bien.
  - `comun.EmbeddingDev` (§5.11): las llamadas que `encender` repite mientras espera (`describe-services`, `list-tasks`,
    `describe-tasks`, `get-instances-health-status`, `get-metric-statistics`, `describe-alarms`) pasan por
    `_sondear`: `InstanceNotFound` y los límites de peticiones (`CODIGOS_TODAVIA_NO`) son «todavía no» y se sigue
    esperando hasta el límite; un permiso que falta, `ErrorConfiguracion` (código 3); otro error, `Falla` (código 2
    en P6). Revisadas también `list-tasks` y `describe-tasks` en el arranque: no lanzan por una tarea que aún no está
    (lista vacía o `failures`), pero ahora también toleran el *throttling*.
  - §5.11: la tabla de `EmbeddingDev` y sus constantes, y la «trampa del arranque de `embedding`» nueva; se quita la
    nota de 0.9.0 que decía que esos errores no se traducían.
- **Contratos tocados (§5):** ninguno (solo el validador y su documentación; versión de parche).
- **Cómo se verificó:** `tests/ops/test_validate22.py` con un Cloud Map falso que responde `InstanceNotFound` las
  primeras 3 veces (P6 pasa y vuelve a consultar) y otro que responde `AccessDeniedException` (código 3 y la
  limpieza apaga `embedding`); `ruff check`, `ruff format --check` y la suite completa con `PRUEBAS_DB_OBLIGATORIA=1`.
- **Pendiente:** repetir `validate22.py --entorno dev` (lo corre el maestro, `validation-2-2.md` §5).

## [0.9.0] — 2026-10-25

- **Lote que la motivó:** BE-2.2 (Worker de ingesta).
- **Qué cambió:**
  - §4.6 reescrita con lo construido: arranque (sin configuración, latidos sin consumir), bucle (puerta de
    `/health/ready` antes de recibir, mensajes devueltos si `embedding` se apaga durante la espera larga, borrar o
    retener por mensaje), las dos transacciones por foto con el orden de bloqueo de §4.5, validación y derivados con
    Pillow (EXIF, miniatura, copia reducida sin EXIF), lotes de 4 a `/v1/embed`, comparación de `version_vector` con
    cada respuesta, errores permanentes (tabla de motivos de `imagenes.error`) y transitorios, `intentos`, y la tabla
    «qué ofrece BE-2.2 al código» para BE-2.4, BE-3.1, BE-3.2 y BE-4.1 (`embedding.vectorizar`,
    `AlmacenS3.descargar`/`escribir`, `ColaSqs`, `dominio.imagenes`, `dominio.mensajes`, `servicios.ingesta`,
    `worker.consumir`, el `Mundo` de las pruebas con base).
  - §4.1 y §2: módulos nuevos (`dominio/imagenes.py`, `dominio/mensajes.py`, `servicios/ingesta.py`,
    `clientes/sqs.py`) y Pillow 12.3 en la imagen. §4.2: el `worker` provisional queda como historia. §4.5: el `subir`
    previsto se llama `escribir` (no choca con `almacen_falso.subir`); la fixture `almacen_falso` gana `descargar`,
    `escribir` y bytes por clave.
  - ADR-BE-15 (no recibir sin `embedding`; transitorio = el mensaje se queda; permanente = foto en `error`;
    idempotencia por ETag y `ON CONFLICT`; versión por respuesta; copia sin EXIF). R13 actualizado; R15 nuevo
    (fallos transitorios repetidos → DLQ).
  - §5.11: ayudas de `comun.py` para BE-2.2 (`EmbeddingDev` con el contrato de encendido de infra §5.10,
    `embedding_en_api`, `hora_bogota`, `mensajes_cola`, `enviar_mensaje`, `eventos_worker`) y `validate22.py` como
    ejemplo de validador que enciende `embedding`.
  - `validation/validation-2-2.md` reescrito: P6 (encendido), P4 con la hora de Bogotá (código 3 fuera de hora),
    C1 hasta 20 min (la subida de `worker` tarda de 2 a 15 min, infra ADR-INF-15), C4 y C5 esperan el evento del
    `worker` en su log en vez de los contadores de SQS, C3a espera 45 s tras el apagado antes de subir, C3b enciende
    con el contrato y §5 completo. `validation-2-1.md` §5: con Pillow en las dependencias ya no se omite ninguna prueba.
  - PLAN: alineado con 0.9.0; fila BE-2.2 «En curso».
  - Repaso de los docs contra el código (antes de publicar 0.9.0): §4.6 añade el orden por fases y en serie del lote,
    los nombres internos de `ingesta.py`, `worker.py`, `imagenes.py`, `mensajes.py`, `sqs.py` y `embedding.py`, los
    detalles de `vectorizar` (partes, `X-Request-Id`, sin tope de 8 imágenes, plazo por fase y no total), la API del
    `Mundo` y del doble `Embeddings` de las pruebas con base, el validador falso de `test_validate22.py` y trampas
    nuevas (`catch_warnings` no seguro entre hilos, `monkeypatch` de `procesar_lote`, `Settings` que lee el entorno);
    §5.11, lo que `validate22.py` tiene fuera de `comun.py` (`lote_hecho`, constantes, `Contexto`) y sus trampas
    (`--sin-limpieza` no restaura `embedding`, errores sin traducir en `EmbeddingDev`); §4.3 y §5.10 al día
    (`DB_POOL_WORKER` ya en uso; `REC_LADO_MIN_PX` lo valida el `worker`).
  - JPEG multi-imagen (`MPO`): el repaso destapó que `preparar` rechazaba un JPEG con varias imágenes (Pillow lo abre
    como `MPO`; quedaba en `error` con «no es un JPEG decodificable»). Ahora `preparar` acepta `JPEG` y `MPO`
    (`FORMATOS_ADMITIDOS`) y de un `MPO` procesa solo la primera imagen como un JPEG normal (EXIF incluido); la
    miniatura y la copia para embeddings salen como JPEG de una sola imagen (§4.6, «JPEG multi-imagen»). Pruebas en
    `tests/unit/test_imagenes.py` con un MPO de 2 imágenes hecho con Pillow (con y sin orientación EXIF 6).
  - Contradicciones corregidas: `validation-2-2.md` exigía `procesada` en 10 min, pero la subida de `worker` puede
    tardar hasta 15 (infra §5.10, ADR-INF-15); C3b volvía a 1 con `update-service`, que según el contrato de infra
    §5.10 no basta; P3 mezclaba «EMB-2.1 Hecho» con el encendido; §4.8 dice que BE-2.4 vectoriza con prioridad
    `baja` (el docstring de `clientes/embedding.py` de BE-1.1 no lo decía).
- **Contratos tocados (§5):** §5.8 precisa qué acepta el `worker` (Records `ObjectCreated:*`, `eTag`/`size`
  opcionales, clave con UUID, `reprocesar_imagen` versión 1) y que un evento repetido se borra; §5.9 (`worker` consume
  `ingesta`; sin configuración, solo latidos; variables que lee); §5.10: eventos nuevos `embedding_listo`,
  `embedding_no_listo`, `lote_ingesta`, `mensajes_devueltos`, `imagen_procesada`, `imagen_con_error`,
  `mensaje_descartado`, `mensaje_no_reconocido`, `ingesta_transitoria`, `version_vector_distinta`, `cola_fallida`;
  `worker_iniciado` con `modo = ingesta`; `configuracion_incompleta` también en `worker`; notas de `MINIATURA_*` y
  `WORKER_*`. §5.7: qué cuenta `imagenes.intentos` (sin cambio de esquema). Ningún contrato existente cambia de forma.
- **Cómo se verificó:** en local (WSL), `ruff check`, `ruff format --check` y `pytest` con `PRUEBAS_DB_URL` y
  `PRUEBAS_DB_OBLIGATORIA=1` (todas pasan; las nuevas: `tests/base/test_ingesta_base.py` con PostgreSQL real,
  `almacen_falso` y embeddings simulados para C1–C5; `tests/unit/test_worker.py`, `test_sqs.py`, `test_imagenes.py`,
  `test_mensajes.py`, y `test_cliente_embedding.py` y `test_s3.py` ampliados; `tests/ops/test_validate22.py` con
  AWS, la API y un `worker` simulados). `docker build` de la imagen en local: `import PIL` (12.3.0) y
  `python -m app.worker` sin configuración arranca en `sin_consumo` y para limpio con SIGTERM.
- **Pendiente:** `validate22.py --entorno dev` sobre un commit de `main` desplegado (lo corre el maestro;
  `validation-2-2.md` §5). Sin comprobar en `dev`: qué responde S3 al `GetObject` de una clave inexistente con el rol
  `tarea-worker` (404 o 403), el tiempo real de subida de `worker`, la memoria del `worker` con Pillow y si la app
  (CameraX) produce JPEG multi-imagen (`MPO`; el `worker` ya los acepta).

## [0.8.0] — 2026-10-25

- **Lote que la motivó:** BE-2.1 (Recolección).
- **Qué cambió:**
  - §4.5 reescrita con lo construido: secuencia, paso a `subida` por `HEAD` también en las repeticiones de `images`
    (sin eso, C2 de la validación no se cumple con el `worker` apagado), estado del video derivado de los conteos,
    concurrencia (`SELECT … FOR UPDATE` del video; `HEAD` y firmas fuera de las transacciones), cliente de S3
    (SigV4, direccionamiento virtual, `Content-Type` firmado, credenciales temporales), lectura para el panel,
    `limpiar-validacion` (orden S3 → filas → S3) y la tabla «qué ofrece BE-2.1 al código» para BE-2.2, BE-3.1 y
    BE-4.1 (`dominio.recoleccion`, `recalcular_estado`, `servicios.videos`, `clientes.s3`, `obtener_almacen`,
    `crear_app(almacen=)`, `esquemas.comun`, `esquemas.videos`, fixture `almacen_falso`) y sus trampas.
  - §4.1: estructura real (`api/v1/collect.py` y `admin_videos.py`, `esquemas/comun.py` y `videos.py`,
    `dominio/recoleccion.py`, `servicios/recoleccion.py`, `videos.py` y `limpieza.py`, `clientes/s3.py`); boto3 pasa a
    las dependencias de la imagen. §2: `api` también hace `HEAD` en S3. §4.6 (BE-2.2): la foto puede llegar ya en
    `subida`, el ETag se guarda sin comillas y el estado se recalcula con `recalcular_estado`.
  - ADR-BE-14 (S3 confirma la subida con `HEAD`; estado del video derivado de los conteos). R4 ampliado; R13 (eventos
    de S3 sin consumidor hasta BE-2.2) y R14 (boto3 en `api`) nuevos.
  - §5.11: `comun.py` añade `FAMILIA_WORKER` (y su log group), `EntornoBackend.cli(…, familia=)`, `revision(familia)`,
    `jpeg_sintetico` (JPEG válido sin Pillow), `Validador.ejecutar(…, preparacion=)` y dos eventos en `motivo_cli`;
    cómo se limpian los restos al empezar y por qué el validador no purga la cola `ingesta`.
  - `validation/validation-2-1.md`: P5 (definición de `worker` y red), preparación con los restos, C2b acepta `subida`
    o un estado posterior, C5 tolera que el `worker` haya avanzado, C6b exige `limpieza_rechazada`, §4 con los eventos
    de S3 que quedan en `ingesta` y §5 con variables, preparación y ejecución.
  - PLAN: alineado con 0.8.0 (sin tocar §3).
  - Contradicción corregida: §4.1 nombraba `obtener_limitador_hash`, que no existe; la dependencia es
    `obtener_cola_hash` (como dice §4.4).
  - Tras una revisión independiente (antes de publicar 0.8.0, así que se corrige aquí): (1) C4 exige también el
    `estado` que §5.5 deriva del conteo; (2) orden de bloqueo **video → imágenes** documentado y ayuda pública
    `recoleccion.bloquear_video` para el `worker` de BE-2.2 (evita *deadlocks*); (3) una fecha con zona que al pasar a
    UTC sale de los años 1–9999 daba `500` (asyncpg, `OverflowError`): ahora `422`; (4) P5 exige que la revisión de
    `worker` use la imagen de `api` (código 2 antes de crear nada); (5) C3a espera con la hora de S3 (`Date`), no con el
    reloj local, que en WSL puede ir atrasado; (6) `limpiar_validacion` con una lista vacía ya no puede equivaler a
    «todos»; (7) un fallo de la segunda pasada por S3, ya sin filas, no hace fallar el comando (evento
    `limpieza_s3_incompleta` y cómo borrar los huérfanos); (8) los restos se buscan con el mismo criterio que la CLI y
    en todas las páginas (por eso `VideoResumen` lleva `ref_cliente`); (9) el log de una tarea se relee hasta que llega
    la línea `LIMPIEZA` (`fin_limpieza`) y la limpieza final no la exige si la tarea salió con 0; (10) P4 prueba
    también `list-objects-v2` y un `head-object` de una clave inexistente (permisos = código 3 en la precondición);
    (11) las ayudas reutilizables pasan de `validate21.py` a `comun.py` (`put_prefirmado`, `head_objeto`, `claves_s3`,
    `comprobar_bucket`, `hora_s3`, `desfase_s3_s`, `fin_limpieza`, `limpiar_videos`, `linea_limpieza`,
    `videos_validacion`, `borrar_restos`, `RecorridoPrueba`), con su tabla en §5.11; (12) §4.5 lista lo que falta en
    `AlmacenS3` para BE-2.2 (`descargar`, `subir`) y BE-4.1 (`firmar_get`); (13) la renovación de credenciales queda
    como hipótesis sin comprobar, con su consecuencia; (14) `S3_BUCKET_DATASET` se exige después de comprobar el video
    (inexistente → 404 aunque falte) y §4.5 dice bien que el listado hace dos consultas. Además: `limpiar-validacion
    --simular` (C6b nunca apunta la orden real a un video ajeno) y `max_length` 50 en `images`.
- **Contratos tocados (§5):**
  - §5.4 `POST /v1/collect/videos`: `ref_cliente` y `nombre` se recortan; todos los demás campos opcionales con sus
    rangos (`duracion_s`, `pasos`, `distancia_m` ≤ 1 000 000, `dispositivo` ≤ 200, `app_version` ≤ 40, fechas con
    zona y `finalizado_en` ≥ `iniciado_en`); el `200` idempotente devuelve el video sin cambiarlo; `409 VIDEO_ELIMINADO`
    si el de ese `ref_cliente` está eliminado; campos de más ignorados; fecha fuera de los años 1–9999 en UTC →
    `422`.
  - §5.4 `…/images`: límites como parámetros de §5.10 (más de 50 elementos, siempre `422`), orden de la respuesta =
    el de la petición, orden de los errores (`422` → `404`/`409` → `500` por S3), `HEAD` de las
    repetidas pendientes (pasan a `subida` sin URL), `expira_en` sin fracciones, `403` de una URL vencida con su
    código, errores `422` (UUID), `500` (sin `S3_BUCKET_DATASET` o firma fallida) y `503`.
  - §5.4 `…/complete`: `subida_completa_en` la primera vez, estado devuelto, `HEAD` fallido deja la foto pendiente;
    errores `404`, `409`, `422`, `500`, `503`.
  - §5.5: `VideoResumen` añade `ref_cliente`; reglas del estado del video; `inicio` y demás `null` si no se enviaron; `url`, `url_miniatura` y
    `url_expira_en` siempre `null` hasta BE-4.1; detalle de `GET /v1/admin/videos` (`q` literal, órdenes, desempate,
    paginación, `422`) y de `GET /v1/admin/videos/{id}` (`404` si eliminado).
  - §5.6: `VIDEO_ELIMINADO` cubre registrar, completar y volver a crear; `500 ERROR_INTERNO` también por configuración
    que falta en `api`.
  - §5.7 (solo reglas, sin cambio de esquema ni migración): `subida_completa_en`, `imagenes.bytes` y `etag`.
  - §5.9: `limpiar-validacion` en detalle (prefijo en `nombre` **y** `ref_cliente`, negativa entera, códigos 0–3,
    evento y línea `LIMPIEZA`, segunda pasada que no falla, `--simular` con su evento y la línea `SIMULACION`), cómo se lanza en `dev` con la definición de `worker`, variables `S3_BUCKET_DATASET` y
    `AWS_REGION` en `api`; boto3 en la imagen.
  - §5.10: eventos `video_creado`, `imagenes_registradas`, `subida_completada`, `s3_fallido`, `limpieza_validacion` y
    `limpieza_rechazada`, `limpieza_simulada` y `limpieza_s3_incompleta` (`s3_fallido` con operación `listar`);
    `configuracion_incompleta` y `comando_fallido` amplían su uso; notas de `REC_*`,
    `PRESIGN_PUT_TTL_S` y `PAGINA_*`.
- **Cómo se verificó:** en `local` (WSL, uv 0.13.4 con `--frozen`): `ruff check` y `ruff format --check` limpios;
  `pytest` con PostgreSQL 17.11 + pgvector (`pgvector/pgvector:pg17`, `PRUEBAS_DB_OBLIGATORIA=1`): todo en verde (ver
  el informe del lote), con S3 simulado (`almacen_falso`, `Stubber` de botocore) y el validador contra un mundo falso
  (API, S3, ECS y reloj). `uv.lock` regenerado con uv 0.11.32 (solo añade boto3 a las dependencias principales) y
  `uv sync --frozen --group ops` con 0.11.32 funciona. `docker build` de la imagen y arranque con `S3_BUCKET_DATASET`
  (cliente de S3 creado). JPEG de `jpeg_sintetico` decodificado con Pillow. En `dev`, solo lecturas: rol `tarea-api`
  sin `s3:ListBucket` (de ahí el 403 del `HEAD`), rol `tarea-worker` con `DeleteObject` y `ListBucket` por prefijo,
  definición `campus-locator-dev-worker:4` con `DB_*` y `S3_BUCKET_DATASET`, log group `/campus-locator/dev/worker`.
  `validate21.py --entorno dev` **sin ejecutar** (lo cierra el maestro tras desplegar).
- **Pendiente:** ejecutar `validate21.py` en `dev` sobre el commit desplegado y cerrar PLAN §3. Medir en `dev` el
  tiempo de `complete` con 200 fotos y la memoria de `api` con boto3 (R14). `firmar_get` para BE-4.1 y BE-3.1.

---

## [0.7.1] — 2026-10-25

- **Lote que la motivó:** BE-1.3 (Autenticación), cierre con la validación en `dev`.
- **Qué cambió:** §4.4 y R12 anotan el tiempo del login medido en `dev` (1,1–1,2 s con 0,25 vCPU, una petición a la
  vez) y que, con dos verificando a la vez, los que esperan pueden pasar de los 10 s y recibir `503 SERVICIO_OCUPADO`
  (sin medir). PLAN: BE-1.3 «Hecho».
- **Contratos tocados (§5):** ninguno; aclaración con lo medido. Sube el parche.
- **Cómo se verificó:** `backend.yml` en verde sobre `78bae6d` (`migrate` sin migraciones nuevas, `api` con ese
  commit en `GET /v1/health`; login con correo inexistente → 401). `validate13.py --entorno dev` con código 0
  (2026-10-25 19:51–19:54 UTC, informe `.validacion/BE-1.3-20261025-195440.json`): pasan P1–P5, C1 (HS256, claims de
  §5.2, `exp − iat` = 43 200 s), C2 (cuerpos idénticos; 1168 y 1116 ms), C5, C3, C4a, C4b y C6 (3 fallidos, 2
  correctos, 0 con contraseña); la limpieza dejó desactivado `validacion+user@campus.edu.co`.
- **Pendiente:** el límite de intentos por cuenta (R7, propuesta de infra 0.12.0) espera decisión. `validate13.py`
  provoca un `501` por ejecución: no llega al umbral de la alarma de 5xx de INF-3.1 (> 5 en 5 min), que todavía no
  existe. Opcional para `FRONTEND_KOTLIN`: mostrar el `503 SERVICIO_OCUPADO` como «ocupado, reintenta» en lugar de «sin
  conexión».

---

## [0.7.0] — 2026-10-25

- **Lote que la motivó:** BE-1.3 (Autenticación).
- **Qué cambió:**
  - §4.4 reescrita con lo construido: login uniforme (una consulta, un argon2id contra un hash ficticio si el correo no
    existe, auditoría, sin conexión a la base durante el hash, `LOGIN_HASH_CONCURRENTES`), orden de rechazos de
    `requiere_admin`, usuarios por CLI (con la negativa a dejar sin admin), acceso a la base desde la API
    (`sesion.transaccion`, `es_fallo_de_base`, 503) y por qué no una dependencia con `yield`. Nueva tabla «qué ofrece
    BE-1.3 al código» para BE-2.1 y BE-3.1: `requiere_admin`/`UsuarioActual`, `RUTAS_ADMIN`/`RUTAS_COLLECT`,
    `obtener_motor`, `transaccion`, `auditoria.anotar`, `tokens`, `hash_ficticio`, validaciones y fixtures.
  - §4.1: estructura real (`api/dependencias.py`, `api/v1/auth.py` y `reservados.py`, `seguridad/tokens.py` y
    `dependencias.py`, `servicios/autenticacion.py`, `usuarios.py` y `auditoria.py`, `esquemas/auth.py`); §4.3 remite a
    §4.4 para el acceso a la base desde la API.
  - ADR-BE-13 (login uniforme y autorización con el estado actual de la base). R7 (sin límite de intentos por cuenta:
    pendiente de decisión) y R12 nuevo (argon2id en 0,25 vCPU).
  - §5.11: ayudas nuevas de `comun.py` (`leer_secreto`, `credenciales_admin`, `ClienteApi` con reintentos de 429 de API
    Gateway y pausa entre logins, `EntornoBackend` para la CLI y SQL en `local` y `dev`, el usuario de prueba);
    `ejecutar_proceso` y `lanzar_tarea` aceptan `entorno`; `JWT_SECRET` en `local` para `validate13.py`.
  - `validation/validation-1-3.md`: P6 (compose en `local`), el usuario de prueba se crea dentro de C5 (un fallo es
    `falla`, no un error), C4a cambia un carácter del medio de la firma, C6 compara con los logins que hizo el script,
    reintentos de 429 y §5 con variables, preparación y ejecución.
  - PLAN: alineado con 0.7.0; entregables de BE-1.3 completos (acceso a la base y reservados); BE-1.3 «En curso».
  - Tras una revisión independiente (antes de publicar 0.7.0, así que se corrige aquí): (1) un NUL en `identificador`
    o `password` llegaba a PostgreSQL (22021) y daba `500` sin auditoría: ahora `422 VALIDACION`
    (`validaciones.motivo_texto_no_admitido`, regla para todo texto que llegue a la base); (2) la cola del hash no
    tenía tope ni plazo: `ColaHash` con `LOGIN_HASH_COLA_MAX` y `LOGIN_HASH_ESPERA_MAX_S` y `503 SERVICIO_OCUPADO`;
    (3) la protección del último admin tenía una carrera, contaba admins inactivos, no cubría `desactivar-usuario` y
    `--rol` degradaba en silencio: ahora bloqueo consultivo, solo admins activos, las dos operaciones, `--rol` opcional
    y `INSERT … ON CONFLICT`; (4) la limpieza de `validate13.py` podía dejar activo al usuario de prueba; (5)
    `ClienteApi` reintenta el `500` de API Gateway.
- **Contratos tocados (§5):**
  - §5.2: cabecera, claims exactos y su formato, orden de los rechazos (un `user` desactivado da `401`, no `403`), rol
    mirado también en la base, `WWW-Authenticate: Bearer`, `500` sin `JWT_SECRET`, consecuencias (reactivar devuelve la
    validez a los tokens; cambiar la contraseña no los invalida).
  - §5.3 `POST /v1/auth/login`: límites de `identificador` (1–320) y `password` (1–256), sin NUL ni sustitutos sueltos,
    campos de más ignorados, cuerpo fijo del `401`, `400`, `503 BASE_NO_DISPONIBLE`, `503 SERVICIO_OCUPADO` con
    `Retry-After: 5` y `500`; solo se audita el intento en el que se comprueba la contraseña. Endpoints reservados:
    existen desde BE-1.3 (antes `404`).
  - §5.6: código nuevo `503 SERVICIO_OCUPADO`; `BASE_NO_DISPONIBLE` en cualquier endpoint que use la base;
    `WWW-Authenticate` en los 401 de token.
  - §5.7: `usuario.crear`, `usuario.actualizar` y `usuario.desactivar` en el catálogo de `auditoria`; forma de las filas
    de BE-1.3 (un rechazo por saturación no se anota); `ultimo_acceso_en` = último login correcto; `hash_password`
    remite a §4.3 (decía §4.4). Sin cambios en el esquema.
  - §5.9: `crear-usuario` informa con el evento `usuario_guardado` (decía «imprime `creado` o `actualizado`»); `--rol`
    es opcional (sin él, un usuario existente conserva su rol; uno nuevo es `user`); reglas de `--correo`, `--nombre` y
    la contraseña; ni `crear-usuario` ni `desactivar-usuario` dejan la base sin un admin activo (1, `usuario_rechazado`)
    y van en fila con el bloqueo consultivo `7242031220260002`; cómo lanzarlos en `dev` y `local`; `api` necesita
    `JWT_SECRET` y `CREAR_USUARIO_PASSWORD` entra en las variables.
  - §5.10: parámetros `LOGIN_HASH_CONCURRENTES` (2), `LOGIN_HASH_COLA_MAX` (8) y `LOGIN_HASH_ESPERA_MAX_S` (10);
    eventos `login` (con `resultado = rechazado`), `autorizacion_rechazada`, `usuario_guardado`, `usuario_desactivado`,
    `usuario_no_encontrado`, `usuario_rechazado` y `comando_fallido`; `configuracion_incompleta` también en `api` (sin
    `JWT_SECRET`) y `base_no_disponible` en cualquier endpoint.
  - Endpoint y contenido nuevos sin romper nada desplegado: sube la menor.
- **Código:** dependencia `pyjwt` (2.15.1; `uv.lock` rehecho con uv 0.11.32, el de la imagen y CI, para conservar
  `revision = 3`: solo añade el paquete); `app/seguridad/tokens.py` y `dependencias.py`; `app/api/dependencias.py`,
  `api/v1/auth.py`, `api/v1/reservados.py` y `api/v1/__init__.py` (routers protegidos); `app/esquemas/auth.py`;
  `app/servicios/autenticacion.py`, `usuarios.py` y `auditoria.py`; `app/db/sesion.py` (`transaccion`,
  `es_fallo_de_base`); `app/errores.py` (503 de `BaseNoDisponible` y mensajes nuevos); `app/main.py` (`ColaHash` y
  hash ficticio al arrancar); `app/cli.py` (dos comandos); `app/config.py` (`login_hash_*`);
  `app/dominio/validaciones.py`; `src/ops/validate13.py` y `src/ops/comun.py`.
- **Cómo se verificó** (en WSL, `uv` 0.13 y 0.11.32, Docker 29; nada en AWS):
  - `ruff check` y `ruff format --check` limpios; `uv lock --check` con uv 0.11.32.
  - `pytest` con PostgreSQL 17.11 + pgvector (el `db` del compose) y `PRUEBAS_DB_OBLIGATORIA=1`: 350 pruebas, todas
    pasan (151 nuevas de BE-1.3). Sin base, las 52 con base se omiten; con `PRUEBAS_DB_OBLIGATORIA=1` y sin URL, fallan.
    Las de la revisión: NUL en cada campo → 422 sin auditoría ni `error_api`; cola llena → 503 con `Retry-After: 5`,
    sin tocar la base ni auditar; sin turno a tiempo → `espera_agotada` y los puestos liberados; dos degradaciones a la
    vez de los dos únicos admins → una rechazada; un admin inactivo no cuenta; no se desactiva al último admin activo;
    sin `--rol` se conserva el rol; dos creaciones del mismo correo a la vez → `creado` y `actualizado`; la limpieza de
    `validate13.py` desactiva al usuario si `crear-usuario` falla tras reactivarlo y tolera que no exista; `500` de API
    Gateway reintentado y el del backend no.
    Entre las nuevas: claims exactos, clave usada como texto (HMAC calculado a mano), 13 tokens alterados →
    `TokenInvalido`, vencido por un segundo → `TokenExpirado`; login correcto (claims, `ultimo_acceso_en`, auditoría
    `exito`), los tres fallos con cuerpo y encabezados idénticos, **un** argon2id por intento (contra el hash ficticio
    si el correo no existe) y su auditoría sin contraseña ni identificador; `requiere_admin` (sin token, otro esquema,
    basura, otra clave, vencido, `user`, desactivado, degradado, `sub` desconocido, reactivado; 401 antes que 422; sin
    base 401 o 503 según el token); toda ruta de `/v1/admin` y `/v1/collect` exige el token (por el OpenAPI); conexión
    cortada a mitad de transacción → 503 y nada confirmado; un *timeout* de httpx no es «base no disponible»; CLI
    (crear, actualizar, reactivar, desactivar, último admin, sin esquema, contraseña por variable y terminal, códigos 2
    y 3); contrato (§5.2 claims, ejemplos y cuerpo fijo de §5.3, códigos de §5.6, parámetros y **todos** los eventos que
    registra el código frente a §5.10); `validate13.py` contra una API falsa que firma con `app.seguridad.tokens`
    (dev completo, 429 de API Gateway, cuerpos distintos, backend que no mira `activo`, firma con la clave decodificada,
    limpieza, `local`, sin secretos en la salida) y las ayudas nuevas de `comun.py`.
  - `docker compose up --build` (la imagen instala `pyjwt` con `uv sync --frozen`), `migrar` y
    `validate13.py --entorno local`: código 0 con las siete comprobaciones en `[PASA]`, dos veces seguidas;
    `validate12.py --entorno local` sigue en 0. Ni el informe ni los logs de `api` contienen contraseñas ni tokens.
    Contra la misma imagen: un NUL en `identificador` da `422` con `No puede contener el carácter NUL.`, y 30 logins a
    la vez dieron 25 `401` y 5 `503 SERVICIO_OCUPADO` con `Retry-After: 5`.
  - Tiempos del login en `local` (15 muestras por caso, sin límite de CPU): mediana 92,9 ms (correo desconocido), 92,5
    (contraseña incorrecta), 92,4 (inactivo) y 94,2 (correcto).
- **Pendiente:**
  - Desplegar (`backend.yml`) y ejecutar `validate13.py --entorno dev`; anotar los tiempos de C2 en `dev` (R12). Sin
    comprobar en `dev`: si una avalancha de logins deja sin CPU el *health check* (R12).
  - La app trata hoy cualquier 5xx como «sin conexión» (`FRONTEND_KOTLIN` §5.10): `503 SERVICIO_OCUPADO` con
    `Retry-After` podría mostrarse como «ocupado, reintenta»; es opcional y lo decide el frontend.
  - Decidir el límite de intentos de login por cuenta que propone infra (su CHANGELOG 0.12.0, R10): no entra en
    BE-1.3 (R7).

---

## [0.6.1] — 2026-10-25

- **Lote que la motivó:** BE-1.2, al cerrarlo. Una auditoría del documento contra el código (otra sesión, leyéndolo
  como quien hará BE-1.3, sin abrir el código) encontró frases que no coincidían con el código y cosas que solo se
  sabían leyéndolo.
- **Qué cambió:**
  - §4.3, «Para los lotes siguientes» (nuevo): lo que BE-1.2 ofrece al código. Conexión (`crear_motor`, `conectar`,
    `comprobar_conexion`, `es_fallo_de_conexion`, `describir`, `app.state.motor`), modelos, el tipo `Vector`,
    enumerados, hash de contraseñas (formato y parámetros) y normalización del correo. Cómo escribir una migración
    nueva: archivo y revisión, una sentencia por `op.execute`, `downgrade`, sin `alembic.ini`, archivos que cambian
    juntos, qué comprueban las pruebas, compatibilidad con la imagen anterior y nombre del índice HNSW de otra versión.
  - §4.3, `migrar`: las revisiones pendientes van en una transacción y el admin inicial en otra, después (si el admin
    falla, la base ya queda migrada); con el bloqueo ocupado más de 5 min termina con 1; clave del bloqueo. Con la
    conexión abierta, también son «base no disponible» 57P01, 57P03, el tiempo agotado y las conexiones perdidas.
    Pruebas con base: formato de `PRUEBAS_DB_URL`, permisos, cuándo se omiten y cuándo fallan, fixtures.
  - §4.4: BE-1.3 añade la dependencia de acceso a la base (abierta con `conectar`) y el manejador que convierte
    `BaseNoDisponible` en `503 BASE_NO_DISPONIBLE` (hoy acabaría en `500`); el correo se normaliza quitando solo los
    espacios de alrededor.
  - §4.1: `.dockerignore` también deja pasar `migrations/`; remite a §4.3 para lo que ofrecen `db/`, `dominio/` y
    `hash.py`.
  - §4.2: `asyncio` también queda en `WARNING`.
  - §5.11: el código común de los validadores (`Validador`, excepciones, ayudas de AWS y de tareas sueltas).
  - `validation/validation-1-2.md`: remite a §5.11 en lugar de nombrar funciones.
  - PLAN: alineado con 0.6.1.
- **Contratos tocados (§5):** ninguno cambia; se corrige cómo estaban escritos.
  - §5.7 `usuarios.nombre`: el `CHECK` es `btrim(nombre) <> ''`, así que tampoco admite solo espacios; decía «no
    vacío».
  - §5.9: el código 2 de `verificar-esquema` también llega con `verificacion_fallida`; un error de argumentos (3) escribe
    el uso y el error en stderr, sin evento; `migrar` también termina con 1 si espera más de 5 min el bloqueo; valores
    admitidos y por defecto de `DB_SSLMODE` y `DB_PORT`, y qué pasa con un valor no válido.
  - §5.10: `migracion_fallida` incluye la espera agotada del bloqueo.
- **Cómo se verificó:** cada afirmación nueva, contra el código validado (`684f233`), por quien la escribió y por una
  segunda revisión independiente, que encontró ocho imprecisiones en el borrador (manejo de excepciones de los
  validadores, qué reconoce `es_fallo_de_conexion` al abrir, alcance de la prueba de contrato, reintentos del log,
  entre otras), corregidas antes de entregar. Las pruebas de contrato (§5.7 del documento frente a `esquema.py`) y
  `pytest` sin base pasan con el documento nuevo.
- **Pendiente:** nada. Lo que la 0.6.0 dejaba pendiente quedó hecho: `backend.yml` en `main` con CI en verde sobre
  `684f233` (PostgreSQL 17 confirma los textos de `esquema.py`) y `validate12.py --entorno dev` con código 0 el
  2026-10-25.

---

## [0.6.0] — 2026-10-24

- **Lote que la motivó:** BE-1.2 (Base de datos y migraciones).
- **Qué cambió:**
  - §4.1: estructura real de `db/`, `cli.py`, `servicios/migracion.py`, `dominio/`, `migrations/` y `tests/base/`.
  - §4.2: `backend.yml` instala el grupo `ops`, prueba con un PostgreSQL efímero y registra también la revisión de
    `migrate`.
  - §4.3: cómo funcionan el motor (TLS, tiempo de conexión, `api` arranca sin base), `migrar` (bloqueo consultivo,
    transacción, admin inicial solo si no hay ninguna fila `admin`, conflicto si el correo es de un `user`),
    `verificar-esquema` (solo lectura, eventos), la coherencia migración/modelos/`esquema.py`, las pruebas con base
    (`PRUEBAS_DB_URL`, `PRUEBAS_DB_OBLIGATORIA`) y el paso `migrate` de `backend.yml` con los permisos de `gha-deploy`.
  - §4.1 y §5.10: los logs tampoco llevan valores de sentencias SQL (`hide_parameters`, `DETAIL` de PostgreSQL omitido en
    las trazas).
  - R11: el texto del catálogo depende de la versión mayor de PostgreSQL.
  - `validation/validation-1-2.md`: qué precondiciones se evalúan en cada entorno, C1 exige que el segundo `migrar` no
    aplique nada, C2 copia los eventos `esquema_diferencia` y distingue el código 2, detalles de las tareas sueltas
    (`startedBy`, streams), herramientas y cómo se ve una ejecución sin despliegue previo.
  - PLAN: alineado con 0.6.0; BE-1.2 pasa a «En curso».
- **Contratos tocados (§5):**
  - §5.7 (completa lo que no fijaba; `verificar-esquema` compara contra exactamente esto): nulabilidad y valores por
    defecto de todas las columnas; restricciones `CHECK` (rangos y longitudes de §5.7, WGS84, rumbo, no negativos,
    `s3_key = dataset/{video_id}/{id}.jpg`, `imagen_key = lugares/{id}.jpg`, coherencia del borrado de videos, `error`
    solo con `estado = 'error'`, `vigencia_hasta > vigencia_desde`, `detalle` objeto); nombres de restricciones e índices
    con la convención de PostgreSQL; índices nuevos `imagenes_lugar_id_idx` (ya decía «índice») y
    `eventos_localizacion_creado_en_idx` (retención); secuencias `videos_numero_seq` (`integer`),
    `eventos_localizacion_id_seq` y `auditoria_id_seq`; `origen`, `resultado` y `nivel` de `eventos_localizacion` como
    `text` con `CHECK` (no tipos enumerados); FK de `auditoria.actor_id` a `usuarios`; `alembic_version`.
  - §5.3 `GET /v1/health/ready`: desaparece `db = no_configurada` (solo existía en BE-1.1); sin `DB_*` o sin respuesta
    de la base en `DB_CONNECT_TIMEOUT_S`, `503 BASE_NO_DISPONIBLE`. La app no usa este endpoint (§5.3: diagnóstico).
  - §5.9: rutas de la imagen (`/srv/app`, `/srv/migrations`), códigos de salida de `migrar` y `verificar-esquema` y
    tabla común de `python -m app.cli` (0 hecho, 1 negativo, **2 base no disponible**, 3 uso o configuración; argparse
    usaría 2 y se cambia a 3). `verificar-esquema` ya no «imprime» diferencias: son eventos de log.
  - §5.10: parámetro `DB_CONNECT_TIMEOUT_S` (5 s) y eventos `base_no_disponible`, `configuracion_incompleta`,
    `migracion_iniciada`, `migracion_terminada`, `migracion_fallida`, `esquema_diferencia`, `esquema_verificado` y
    `verificacion_fallida`.
  - §5.11: en `local`, la base se migra con `docker compose run --rm api python -m app.cli migrar`.
  - Cambio incompatible en §5.3 (un valor que desaparece); mientras la versión sea `0.x`, sube la menor.
- **Código:** dependencias `sqlalchemy[asyncio]`, `asyncpg`, `alembic` y `argon2-cffi` (`uv.lock` solo añade
  paquetes); `src/app/db/` (`sesion.py`, `modelos.py` con un tipo `vector` propio, sin el paquete `pgvector` que
  arrastraría numpy, `esquema.py`), `src/app/cli.py`, `src/app/servicios/migracion.py`, `src/app/seguridad/hash.py`,
  `src/app/dominio/enumerados.py` y `validaciones.py`; `src/app/logs.py` (trazas sin el `DETAIL` de PostgreSQL); `migrations/` (`env.py` y `versions/0001_esquema_inicial.py`);
  `/v1/health/ready` con la base; `config.py` (`db_connect_timeout_s`); `Dockerfile` y `.dockerignore` con
  `migrations/`; `docker-compose.yml` con `ADMIN_INICIAL_*` locales; `src/ops/validate12.py` y, en `src/ops/comun.py`,
  `ejecutar_proceso`, `lanzar_tarea`, `leer_log`, `red_tareas` y `ResultadoTarea`; `.github/workflows/backend.yml`.
- **Cómo se verificó:**
  - Revisión independiente del código (otra sesión, sin ver cómo se escribió). Encontró cuatro defectos, corregidos y
    con prueba: (1) un error al insertar el admin dejaba el hash argon2id y el correo en la traza del log, tanto por los
    parámetros de SQLAlchemy (ahora `hide_parameters`) como por el `DETAIL` de PostgreSQL (ahora omitido en toda traza);
    (2) `DB_PORT=abc` o la falta de `migrations/` salían con código 1 y una traza suelta (ahora 3 con
    `configuracion_incompleta`, o 1 con `migracion_fallida`); (3) la clasificación de fallos de conexión tomaba un
    `FileNotFoundError` o un `PermissionError` por «base no disponible» y no contaba la falta de permiso `CONNECT` ni la
    clase 08 (ahora todo fallo al abrir la conexión es 2 y, después, solo los de red y la clase 08); (4)
    `verificar-esquema` podía decir «difiere» durante un `migrar` (ahora espera su bloqueo). Además, `ready` informaba
    «faltan DB_*» con un `DB_SSLMODE` no válido.
  - `ruff check` y `ruff format --check` limpios. `pytest`: 199 pruebas con PostgreSQL 16.15 y pgvector 0.6.0
    (`PRUEBAS_DB_URL`) y el grupo `ops`; sin base ni `ops`, 142 pasan y 34 se omiten; con `PRUEBAS_DB_OBLIGATORIA=1` y
    sin base, las 32 pruebas con base fallan. Entre ellas: la migración y los modelos dejan exactamente `esquema.py`
    (0 diferencias), §5.7 del documento coincide con `esquema.py` (tablas, columnas, tipo, nulo y valor por defecto,
    tipos enumerados y nombres citados), `migrar` es idempotente y dos a la vez van en fila, admin inicial (correo
    normalizado, argon2id, no revive un admin desactivado, 3 sin variables, 1 si el correo es de un `user`),
    `verificar-esquema` detecta 15 cambios hechos a mano y no modifica nada, las restricciones rechazan datos
    incoherentes, un vector de 384 ida y vuelta, y `/v1/health/ready` con base, sin base y con credenciales malas.
  - CLI contra un PostgreSQL real: código 2 con conexión rechazada, contraseña incorrecta, base inexistente, tiempo
    agotado y TLS rechazado; 0 con `DB_SSLMODE=require` contra un servidor con TLS; 3 sin `DB_*`, con `DB_SSLMODE` no
    válido y con un argumento desconocido.
  - Imagen simulada fuera de Docker (solo las dependencias de producción de `uv.lock`, código en `/srv`): `migrar`,
    `verificar-esquema` y `uvicorn` con el comando de §5.9; `ready` da 200 con base y 503 `BASE_NO_DISPONIBLE` sin ella,
    con su `X-Request-Id` y el evento `base_no_disponible`.
  - `backend.yml`: `actionlint` con `shellcheck`. El job de despliegue se ejecutó con `aws`, `docker` y `sleep`
    simulados (23 escenarios): las entradas de `register-task-definition` y `run-task` se validaron contra el modelo de
    botocore 1.43 y `--query` se aplicó con JMESPath; todas las llamadas están en los permisos de `gha-deploy`; `run-task`
    no lleva etiquetas; `migrate` conserva su comando; si `migrate` sale con 1, no arranca, `run-task` no lanza la tarea
    o no para a tiempo, el workflow falla sin tocar `api` ni `worker`; un log que nunca llega no impide un `migrate`
    con 0; sin `SUBREDES_TAREAS` o `SG_MIGRATE`, falla antes de llamar a AWS.
  - `validate12.py` con AWS, HTTP y Docker simulados (17 pruebas): `dev` y `local` completos, C2 «difiere» frente a
    «no se pudo verificar», migrate con otra imagen que `api`, segundo `migrar` que aplica, contenedor que no arranca,
    RDS 16.4 o en `modifying` (código 2), sin outputs de red (2), sin `AWS_PROFILE` (3), y nunca imprime la contraseña
    del secreto.
- **Pendiente:** colocar `.github/workflows/backend.yml` (las herramientas de edición no pueden escribir en
  `.github/workflows/`) y subirlo a `main`; la primera ejecución de CI, con PostgreSQL 17, confirma los textos del
  catálogo de `esquema.py` (aquí se probó con 16, R11); ejecutar `validate12.py --entorno dev` cuando `backend.yml`
  termine en verde.

---

## [0.5.1] — 2026-10-24

- **Lote que la motivó:** BE-1.1. La primera validación en `dev` falló en C1–C3 porque `.github/workflows/backend.yml`
  no estaba en el repositorio: el servicio `api` nunca se había desplegado (imagen `bootstrap`, 0 réplicas).
- **Qué cambió:**
  - §4.2 describe `backend.yml` tal como queda: disparadores (también su propio archivo), pruebas antes de desplegar
    y sin base hasta BE-1.2, convenciones de `infra.yml` (permisos mínimos, acciones fijadas por SHA, uv 0.11.32),
    *login* en ECR con los permisos de `gha-deploy`, campos que se quitan al registrar una revisión (incluido
    `deleteRequestedAt`, que añadió la API de ECS), espera de hasta 2 min a `COMPLETED` y cómo volver a desplegar el
    mismo commit.
  - BE-1.1 C3a (`validate11.py` y `validation/validation-1-1.md`): además del último commit que tocó `project/`, acepta
    un commit posterior de `main` con `project/` idéntico. `backend.yml` se dispara también con su propio archivo, y un
    commit que solo lo toca despliega el mismo código con otro SHA; antes C3a lo rechazaba.
  - `validation/validation-1-1.md` §5: `AWS_PROFILE` obligatoria aunque se use el perfil `default`, y cómo se ve una
    ejecución sin despliegue previo.
  - PLAN §3: nota de BE-1.1 con el estado real.
- **Contratos tocados (§5):** ninguno.
- **Cómo se verificó:** `actionlint` con `shellcheck` sobre `backend.yml`. Los pasos del job de despliegue se
  ejecutaron con `aws` y `docker` simulados: la entrada de `register-task-definition` se validó contra el modelo de
  botocore 1.43 y `--query` se aplicó con JMESPath. Escenarios: primer despliegue (`api` de 0 a 1, `worker` conserva
  su comando), reintento con la imagen ya publicada (no reconstruye ni toca réplicas), *rollback* de `api` (falla),
  familia sin contenedor `app` (falla antes de registrar) y variable del repositorio ausente (falla sin llamar a AWS).
  En un entorno aparte: `uv sync --frozen`, `ruff check`, `ruff format --check` y `pytest` (65 pruebas, sin base de
  datos; 6 nuevas de C3a sobre un repositorio git temporal), los mismos comandos del job de pruebas. C3a contra el
  historial real: el SHA de `origin/main` (`0990740`, solo infraestructura) y `26db1e2` pasan; `41d1461` (`project/`
  distinto) y `bootstrap` fallan.
- **Pendiente:** colocar `.github/workflows/backend.yml` (las herramientas de edición no pueden escribir en
  `.github/workflows/`), subirlo a `main` y ejecutar `validate11.py` en `dev` cuando el workflow termine en verde.

---

## [0.5.0] — 2026-10-24

- **Lote que la motivó:** ninguno; sin cupo de GPU, `embedding` corre en Fargate con 2 vCPU y con DINOv2 ViT-S/14
  (`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` 0.9.0, ADR-INF-14; `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` 0.5.0,
  ADR-EMB-11). El encendido bajo demanda de 0.4.0 no cambia.
- **Qué cambió:**
  - §3, §4.5, §5.3: «GPU» pasa a «`embedding`»; el script de infra es `embedding.py`.
  - §4.10: se esperan ≤ 800 ms de embeddings para 5 fotos (antes ≤ 500 ms en GPU); el límite duro sigue en 5 s.
  - §5.11: los validadores esperan hasta 10 min (antes 15) a que `embedding` quede listo.
  - R2: la mitigación es el modelo pequeño en 2 vCPU y las palancas de embeddings §4.4.
  - PLAN: BE-3.2 C3 sin «GPU». Validaciones 2-2, 2-3, 2-4, 3-2 y 4-1: encendido de ~3 min; 3-2 C3 comprueba
    `cpu = "2048"` y `memory = "4096"` para `embedding`.
- **Contratos tocados (§5):**
  - §5.7: `embeddings.vector` pasa a **`vector(384)`** y el índice parcial a `embeddings_hnsw_dinov2_vits14_pp_v1`
    sobre `version_vector = 'dinov2-vits14/pp-v1'`.
  - §5.10: `EMBEDDING_VERSION_VECTOR` = **`dinov2-vits14/pp-v1`**; nota de `EMBEDDING_TIMEOUT_S`.
  - §5.3 y §5.5: `version_vector` de los ejemplos.
  - No hay vectores guardados todavía, así que no hace falta re-indexar. Cambio incompatible con 0.4.0 en el esquema;
    mientras la versión sea `0.x`, sube la menor.
- **Código:** `src/app/config.py` (`embedding_version_vector = "dinov2-vits14/pp-v1"`, `embedding_timeout_s = 5.0`;
  el 20 → 5 venía de 0.4.0) y `tests/unit/test_config.py`.
- **Cómo se verificó:** revisión cruzada con embeddings 0.5.0 (§5.2–§5.4) e infra 0.9.0 (§3.4, §5.10, §5.11); 59
  pruebas en verde, `ruff check` y `ruff format --check` limpios.
- **Pendiente:** la primera migración (BE-1.2) debe crear `vector(384)`.

---

## [0.4.0] — 2026-10-24

- **Lote que la motivó:** ninguno; el equipo pide que `POST /v1/localize` responda en menos de 1 s, y la
  infraestructura pasa `embedding` a una GPU bajo demanda, apagada por defecto, en lugar del horario fijo de `dev`
  (`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` 0.7.0, ADR-INF-13).
- **Qué cambió:**
  - §3: `embedding` apagado por defecto y encendido a mano; `worker` escala solo con `embedding` encendido; desaparece
    el horario de `dev`.
  - §4.5 y §5.3: «fuera de horario» pasa a «con la GPU apagada».
  - §4.10: presupuesto de tiempo con `EMBEDDING_TIMEOUT_S` (5 s) y objetivo p95 en el servidor ≤ 1 s (antes p95 total
    ≤ 5 s).
  - §5.11: los validadores que necesitan `embedding` lo encienden si está apagado y lo dejan como estaba (infra §5.11).
  - R2: el riesgo pasa a superar 1 s en el servidor; la mitigación principal es la GPU.
  - Ejemplos de `latencia_ms` (localización y diagnóstico de vecinos) acordes con la GPU.
  - PLAN: BE-3.2 C3 mide p95 de `integrationLatency` ≤ 1 s con `embedding` en su GPU.
  - Validaciones 2-2, 2-3, 2-4, 3-2 y 4-1: en lugar de exigir el horario, encienden `embedding` si hace falta y solo
    piden empezar con margen antes del apagado de las 22:00. 2-2 C3b espera hasta 15 min a que `embedding` vuelva. 3-2
    C3 comprueba el tamaño con GPU (3 vCPU, 12 GB, una GPU) y mide en los *access logs* de API Gateway, no en el
    cliente.
- **Contratos tocados (§5):** §5.3 (`/v1/health/ready`: solo redacción; `POST /v1/localize`: el
  `503 EMBEDDING_NO_DISPONIBLE` por lentitud llega a los 5 s en lugar de 20 s, y ejemplo de `latencia_ms`), §5.5
  (ejemplo de `latencia_ms` del diagnóstico de vecinos), §5.10 (`EMBEDDING_TIMEOUT_S` 20 → 5), §5.11. Ningún cambio incompatible en la API: sube la menor.
- **Cómo se verificó:** revisión cruzada con infra 0.7.0 (§3.4, §5.4, §5.10, ADR-INF-13) y embeddings 0.4.0 (§4.4,
  §5.7, ADR-EMB-10). Sin código: lo cambiado entra con BE-2.2 y BE-3.2.
- **Pendiente:** si `docker-compose.yml` de `local` usa embeddings en CPU para probar `/v1/localize`, subir allí
  `EMBEDDING_TIMEOUT_S` (lo hace el lote que implemente la localización, BE-3.2).

---

## [0.3.0] — 2026-10-23

- **Lote que la motivó:** BE-1.1 (Base del servicio). El código se escribió antes que este cambio; ambos van en el
  mismo PR para que contrato y código se revisen juntos.
- **Qué cambió:**
  - Encabezado: ya hay código (desde BE-1.1).
  - §3 y §4.1: `migrate` en `backend.yml` desde BE-1.2; estructura real de `project/` (`logs.py`, `middleware.py`,
    `errores.py`, `.dockerignore`, `uv.lock`, `.python-version`, pruebas de los validadores).
  - §4.2: cómo funcionan el middleware, los manejadores de error y los logs; `worker` provisional (solo latido, sin
    consumir colas hasta BE-2.2); lo propio del backend en `backend.yml` (publicación idempotente de la imagen, revisión
    que parte de la última de su familia, primer despliegue, comprobación de la revisión tras `services-stable` y job
    sin `environment:` por la confianza del rol `gha-deploy`).
  - §5.1: reglas de `X-Request-Id` (se reutiliza solo con 1 a 128 caracteres `[A-Za-z0-9._:-]`; si no, UUID v4; también
    en los `500`), cuerpo de error con la clave `error` sola y rutas sin redirección por barra final.
  - §5.3: `GET /v1/openapi.json` y `GET /v1/docs` fuera de `prod`; qué son `version` y `commit` en `/v1/health`;
    cuándo `embedding` es `ok` en `/v1/health/ready`.
  - §5.6: fila para `405` (`SOLICITUD_INVALIDA` con `detalle.metodos_permitidos` y encabezado `Allow`); una ruta que no
    existe es `404 NO_ENCONTRADO`; regla para otros estados del framework (4xx → `SOLICITUD_INVALIDA`, 5xx →
    `ERROR_INTERNO`).
  - §5.9: tabla de la imagen (base, código, usuario) y `APP_COMMIT`, fijado con `--build-arg GIT_COMMIT`;
    `migrations/` entra en la imagen desde BE-1.2; ninguna variable es obligatoria para arrancar.
  - §5.10: nombres de los cortes de nivel (`LOC_NIVEL_ALTA_MIN`, `LOC_NIVEL_MEDIA_MIN`) y del pool (`DB_POOL_API`,
    `DB_POOL_API_DESBORDE`, `DB_POOL_WORKER`), que §5.9 permite sobrescribir con variables; formato de log en detalle y
    catálogo de eventos (`peticion`, `error_no_controlado`, `error_api`, `api_*`, `worker_*`, `latido`).
  - §5.11: uso de `docker-compose.yml` en `local` (perfil `embedding`, puertos, `GIT_COMMIT`).
  - `validation/validation-1-1.md`: P3 y P5 terminan con código 3 cuando falla una herramienta, credencial o permiso
    (infra §5.11); C2b envía su propia petición si C2a se omitió con `--solo`.
  - PLAN: BE-1.1 incluye el `worker` provisional y pasa a «En curso».
- **Contratos tocados (§5):** §5.1, §5.3 (rutas nuevas de documentación), §5.6 (405 y regla general), §5.9, §5.10,
  §5.11. Ningún cambio incompatible: sube la menor.
- **Cómo se verificó:** 59 pruebas (API, contrato contra los esquemas de §5.1 y §5.3, unitarias y de los validadores),
  `ruff check` y `ruff format --check`; `actionlint` con `shellcheck` sobre `.github/workflows/backend.yml`; la
  transformación de la definición de tarea, contra el modelo de `RegisterTaskDefinition` de botocore; la imagen,
  simulada fuera de Docker (mismas dependencias de `uv.lock`, mismo comando de §5.9 y el *health check* de infra §5.7):
  logs JSON, `X-Request-Id`, 404 y parada del `worker`; `validate11.py` completo con AWS simulado (código 0 y, con otro
  commit desplegado, código 1).
- **Pendiente:** construir la imagen con Docker (no se pudo en el entorno donde se escribió) y ejecutar `validate11.py`
  en `dev`, que espera INF-1.3 e INF-1.4.

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
