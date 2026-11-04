# CHANGELOG — App Android (`FRONTEND_KOTLIN`)

Una entrada por versión de [`ARCHITECTURE.md`](./ARCHITECTURE.md), la más reciente primero.

**Cómo se numera la versión del documento**
- **Mayor:** cambio incompatible en un contrato de §5 (firma de una pieza reutilizable, función de un puente WebView,
  formato del almacenamiento local, ruta de navegación). Mientras la versión sea `0.x`, un cambio incompatible sube la
  **menor**.
- **Menor:** vista, pieza o contrato nuevos; decisión nueva (ADR); reorganización del documento.
- **Parche:** aclaraciones, correcciones de redacción o entradas que pasan de ⚠ a verificadas sin cambiar el contrato.

Las historias de usuario del catálogo de `PLAN.md` §5 también se versionan aquí cuando cambian.

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

## [0.3.0] — 2026-10-23

- **Lote que la motivó:** ninguno; cambio de organización del monorepo pedido por el equipo.
- **Qué cambió:**
  - El código de la carpeta irá en `project/` y la documentación en `docs/`, con una carpeta nueva
    `docs/validation/` (un documento por lote) y un validador por lote en `project/src/ops/validate<fase><n>.py`.
  - Los lotes se renumeran como `<PREFIJO>-<fase>.<n>` para que el nombre de su validación coincida con el lote
    (`validation-2-2.md` ↔ `validate22.py` ↔ lote x-2.2).
  - El PLAN separa las dependencias «para construir» de las «para validar», numera los criterios de cierre (C1, C2…)
    y añade a §3 las columnas «Validación» y «Última validación».
  - El proyecto Gradle pasa a `FRONTEND_KOTLIN/project/`; la ruta base del código Kotlin es
    `project/app/src/main/java/com/example/myapplication/` (§3.2 describe la carpeta completa).
  - La fase «P» del prototipo pasa a ser la fase 0; sus lotes, FE-0.1 a FE-0.12, quedan cerrados sin validación
    automática.
  - Nuevo §5.11: cómo validan los scripts de la app (Gradle, `adb` con dispositivo físico, comprobaciones estáticas y la
    API de `dev`).
  - FE-4.2 (Ajustes) tiene ahora criterios de cierre.
  - Tras escribir los documentos de validación: §5.10 define la cola de subida (el propio `manifest.json`, con
    `remote_video_id` y `subida_estado`), la base Room `campus_locator.db`, cuándo se sincronizan las alertas y dónde
    se anuncian; §5.11 aclara que no hay backend local (solo HTTPS) y que `connectedDebugAndroidTest` borra los datos
    de la app.
  - `MapaPublicoScreen` no tiene ruta hoy (⚠ verificar en `AppNav`); FE-3.1 le da la ruta pública `mapa`.
  - `CONSERVAR_FOTOS = false` pasa de FE-4.3 a FE-3.2 (FE-4.3 queda con C1–C5); FE-1.2 C3 se comprueba con
    `SesionVencidaTest`; FE-3.4 C2 deja de depender de `/v1/localize` (y de BE-3.2); las pruebas de los criterios
    tienen nombre de clase; FE-2.1 no borra el recorrido que valida: es dataset real.
- **Contratos tocados (§5):** §5.10 (cola de subida, caché de alertas), §5.11 (nuevo). Ninguna pieza de la app cambia
  de firma.
- **Equivalencia de identificadores** (las entradas anteriores usan los viejos): FE-01 → FE-0.1 · FE-02 → FE-0.2 · FE-03
  → FE-0.3 · FE-04 → FE-0.4 · FE-05 → FE-0.5 · FE-06 → FE-0.6 · FE-07 → FE-0.7 · FE-08 → FE-0.8 · FE-09 → FE-0.9 · FE-10
  → FE-0.10 · FE-11 → FE-0.11 · FE-12 → FE-0.12 · FE-13 → FE-1.1 · FE-14 → FE-1.2 · FE-15 → FE-2.1 · FE-16 → FE-2.2 ·
  FE-23 → FE-2.3 · FE-17 → FE-3.1 · FE-18 → FE-3.2 · FE-19 → FE-3.3 · FE-20 → FE-3.4 · FE-25 → FE-3.5 · FE-21 → FE-4.1 ·
  FE-22 → FE-4.2 · FE-24 → FE-4.3 · FE-26 → FE-5.1 · FE-27 → FE-5.2 · FE-28 → FE-6.1.
- **Cómo se verificó:** comprobación automática de que los lotes citados existen, de que las referencias cruzadas entre
  secciones resuelven, de que cada documento de validación cubre una vez cada criterio de su lote y de que las tablas
  están bien formadas.
- **Pendiente:** escribir los validadores (cada lote los entrega con su código); mover físicamente el proyecto Gradle a
  `project/`.


---

## [0.2.0] — 2026-10-23

- **Lote que la motivó:** ninguno de la app; reorganización de la documentación del monorepo en tres documentos por
  carpeta (`docs/ARCHITECTURE.md`, `docs/PLAN.md`, `docs/CHANGELOG.md`) y alineación con los contratos nuevos de
  `BACKEND_FASTAPI` v0.1.0, `SERVICE_EMBEDDING` v0.1.0 e `INFRASTRUCTURA_TERRAFORM` v0.1.0.
- **Qué cambió:**
  - El documento se mudó de `FRONTEND_KOTLIN/ARCHITECTURE.md` a `FRONTEND_KOTLIN/docs/ARCHITECTURE.md`. Las imágenes
    de diseño se enlazan ahora como `../assets/…`. **El archivo anterior debe borrarse** para no tener dos versiones.
  - Nuevo §1 (propósito, regla de contratos, guía de numeración). §1 «Visión general» y §2 se unieron en §2.
    §3 + §4 → §3 (3.1 y 3.2). §5 «Mapa de vistas» → §4. **§11 → §5** (todas las referencias «11.N» se cambiaron a
    «5.N»). §6 y §7 conservan su numeración. §8 → §8.2 (decisiones abiertas, misma numeración) y se añade §8.1 (ADR).
    §9 → §9.2 y se añade §9.1 (riesgos).
  - El antiguo §10 «Estado de implementación», las listas «Pendiente» de las vistas 6.4, 7.3, 7.3b, 7.4, 7.8, 7.9,
    7.11 y 7.14, y el antiguo §11.10 se movieron a `PLAN.md` (lotes FE-01 a FE-28 y tabla de estado §3). En su lugar,
    cada vista conserva su descripción («Implementación actual») y una referencia al lote. Las limitaciones de 7.3b
    siguen en el ARCHITECTURE como «Limitaciones conocidas».
  - La tabla «Responsabilidades del backend (resumen de endpoints)» del antiguo §3 se eliminó: el contrato vive en
    `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5. Diferencias con lo que había aquí: prefijo `/v1` en todas las rutas;
    las fotos del dataset ya no se envían a `POST /collect/videos/{id}/images` sino con URLs prefirmadas;
    `POST /v1/collect/videos/{id}/complete` nuevo; alertas de admin con `PUT` idempotente y
    `POST /v1/admin/alerts/sincronizar`; `GET /admin/videos/{id}/images` pasa a `GET /v1/admin/videos/{id}` (incluye
    las fotos); `GET /admin/stats` es el resumen del panel y las estadísticas de uso quedan en
    `GET /v1/admin/stats/uso` (Fase 5).
  - Decisiones abiertas resueltas por el backend: 7 (privacidad), 10 (borrado de videos) y 11 (autenticación); la 2
    (grafo de caminos) queda aplazada a la Fase 5; la 3 fija el radio por defecto en 15 m; la 9 queda resuelta en parte
    (auditoría). Nuevas decisiones abiertas 17 (nombre del producto), 18 (interacción de Inicio) y 19 (nombre por
    defecto de los videos).
  - ADR-FE-01 a ADR-FE-11 registran decisiones que ya estaban aplicadas en el código; ADR-FE-10 es nueva.
  - El catálogo de historias de usuario (HU-01 a HU-23, propuestas) se crea en `PLAN.md` §5 y es el único del
    proyecto.
- **Contratos tocados (§5):** numeración (§11 → §5). **Nuevo §5.10** «Consumo de la API del backend»: URL base,
  mapeo de errores, mapeo de datos, conversión de rumbo a norte verdadero, subida con URLs prefirmadas y caché de
  alertas. Ninguna pieza existente cambió de firma.
- **Cómo se verificó:** comprobación automática de que cada línea del documento anterior aparece en el nuevo (con la
  numeración cambiada) salvo los bloques movidos a `PLAN.md` y `CHANGELOG.md` y las ediciones listadas arriba;
  revisión cruzada de §5.10 con el §5 del backend. Una revisión independiente posterior movió las tablas de
  `AndroidBridge`, `EditorBridge` y `VideoBridge` a §5.9,
  la estructura de los videos locales (`manifest.json`) a §5.6 y sustituyó los fragmentos de navegación de 7.1, 7.2,
  7.8, 7.11 y 7.14 por referencias a §5.8 (eran copias y una ya estaba desactualizada); también actualizó rutas a
  `/v1`, corrigió afirmaciones que contradecían ADR-FE-04 («sin compilar», sensor de hardware de pasos), alineó el
  tiempo de lectura a 30 s, añadió la re-codificación de fotos antes de subir y pasó `EstadoFoto.PENDIENTE` a FE-15.
- **Pendiente:** implementar §5.10 (FE-13 en adelante); borrar el antiguo `FRONTEND_KOTLIN/ARCHITECTURE.md`;
  confirmar que las imágenes de diseño están en `FRONTEND_KOTLIN/assets/`.

---

## [0.1.0] — 2026-10-12 (reconstruida)

Versión del documento tal como estaba antes de la reorganización (sin número de versión en su momento). Esta entrada
reconstruye su historia a partir de las notas que el propio documento llevaba en su antiguo §11.10. **Usa la
numeración de entonces:** §11 = §5 actual y §10 = `PLAN.md` §3.

- **Lote que la motivó:** construcción del prototipo (lotes FE-01 a FE-12).
- **Qué cambió, por tandas de revisión:**
  - **Tanda 4:** `VideosViewModel.kt`, `LoginViewModel.kt`, `InicioViewModel.kt` (con `BackendHealth`),
    `InicioScreen.kt` y `SeleccionDestinoViewModel.kt` documentados y verificados contra el código (11.5; ajustes en
    11.1, 11.2, 11.3, 11.4 y 11.6 a 11.8).
  - **Tanda 5:** `MainActivity.kt` releído (confirma 11.3 y 11.8), `SeleccionDestinoScreen.kt`, `DestinoUiState` y
    `LoginScreen.kt` (11.5).
  - **Tanda 6 (bache 1):** `BuscarLugares.kt` (con `InterpretarRespuesta` y `Respuesta`), `LugarDestino.kt` (con
    `CategoriaLugar`) y `SeleccionDestinoState.kt` completo (11.5, 11.6 y 11.7).
  - **Tanda 7 (bache 2):** `PanelesVoz.kt`, `ListaLugares.kt` y `Comun.kt` de `ui/destino/componentes/` (11.5 y 11.6).
  - **Tanda 8 (bache 3):** `LugaresRepository.kt` (con `LUGARES_DE_PRUEBA`), `AdminRepository.kt`, `ResumenAdmin.kt`
    y `Usuario.kt` (11.5, 11.6 y 11.7).
  - **Tanda 9 (bache 4, 2026-10-10):** el PDR pasa a Kotlin (`PdrEngine.kt`, `StepDetector.kt`, `PdrTracker.kt`,
    `PuentePdr.kt`, `MapaPublicoScreen.kt`); `app.js` e `index.html` solo dibujan; base común de mapas
    (`mapa_base.js`, `MapaWebView`). ⚠ sin probar en dispositivo.
  - **Tanda 10 (2026-10-11):** vista 7.3 (`UbicacionManualScreen.kt`, `UbicacionManualViewModel.kt`,
    `UbicacionManualState.kt`, `InicioRecoleccion.kt`, `ubicacion_manual.html/js`).
  - **Tanda 11 (2026-10-11):** vista 7.4 (`FotoRecolectada.kt`, `SesionRecoleccion.kt`, `DisparadorCaptura.kt`,
    `RecoleccionRepository.kt`, `RecoleccionState.kt`, `RecoleccionViewModel.kt`, `RecoleccionScreen.kt`,
    `PanelesRecoleccion.kt`, `MapaRecoleccion.kt`, `recoleccion_mapa.html/js`) y rutas nuevas en `AppNav`. Documentado
    a partir de lo entregado, sin releerlo contra el código final.
  - **Tanda 12 (2026-10-12):** vista 7.3b (`CalibracionPaso.kt`, `CalibracionPasoRepository.kt`,
    `CalibracionState.kt`, `CalibracionViewModel.kt`, `CalibracionScreen.kt`, `MapaCalibracion.kt`,
    `calibracion_mapa.html/js`, `CalibracionPasoTest.kt`); longitud de paso inyectable en `PdrEngine` y `PdrTracker`;
    fila «Calibrar mi paso» en 7.3. Ese mismo día los pasos pasan a salir siempre del acelerómetro (se descarta
    `TYPE_STEP_DETECTOR`). Tras compilar el proyecto entero, el aviso «Kotlin sin compilar» de las tandas anteriores
    dejó de aplicar a lo que forma parte del build.
  - Antes de la tanda 4 ya estaban documentados y verificados: `VoiceController` y `ComandoParser`, `SessionManager`,
    `VideoRepository` / `AssetsVideoRepository` / `EdicionesLocales` y `Foto.kt`, `AuthRepository` y `Alerta.kt`,
    `OrientationProvider` y `CapturaFoto`, `ui/ubicacion/componentes/`, `MyApp.kt`, `MainActivity.kt`,
    `EscaneoViewModel.kt` y el resto del escaneo, `FeedbackCaptura.kt`, `AppLog.kt`, `AlertaFormSheet.kt`, el editor
    de mapa (`EditorMapaViewModel.kt`, `EditorMapaScreen.kt`, `editor_mapa.html/js`), el panel, la galería, la lista y
    el detalle de videos (`video_detalle.html/js`) y `CampusColors.kt`.
- **Decisiones de esta etapa:** mapa con OSM + Leaflet en lugar de `eafit.mbtiles`; PDR solo en Kotlin; pasos por
  acelerómetro; calibración del paso por dispositivo; `SesionDeRecoleccion` como *holder* de la recolección; control de
  calidad de imagen desactivado temporalmente (ahora ADR-FE-02 a ADR-FE-07 y ADR-FE-11).
- **Contratos tocados:** puentes `AndroidBridge`, `EditorBridge`, `VideoBridge`, `UbicacionBridge`,
  `RecoleccionBridge` y `CalibracionBridge`; almacenamiento `files/recoleccion/` y `SharedPreferences`
  `campus_calibracion`; rutas `admin/ubicacion-manual`, `admin/calibracion`, `admin/recoleccion` y
  `admin/recoleccion/resumen`.
- **Cómo se verificó:** lectura de los archivos citados por tanda; `CalibracionPaso.kt` y `PdrEngine.kt` con kotlinc
  2.0.21 (13 comprobaciones); páginas web con jsdom; el proyecto completo compila y las vistas 7.3 y 7.3b se abren en
  dispositivo (Xiaomi 23028RA60L, Android 14).
- **Pendiente:** heredado por los lotes de `PLAN.md` (FE-13 a FE-28).
