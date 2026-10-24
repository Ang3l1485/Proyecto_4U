# ARCHITECTURE — Campus Locator

Este documento describe la arquitectura completa del proyecto: qué hace, cómo está
organizado, qué sistemas lo componen y **qué debe tener cada vista** (con el archivo que
la implementa). La sección de vistas está pensada para usarse como brief de diseño
(por ejemplo, para pedirle a una IA que genere los diseños de frontend).

> Ruta base del código: `app/src/main/java/com/example/myapplication/`
> Todas las rutas de archivo de este documento son relativas a esa carpeta.
>
> **Antes de crear o reutilizar algo, consulta la sección 11** (catálogo de piezas reutilizables
> y contratos entre vistas): ahí está cómo usar cada pieza sin tener que leer sus archivos.

---

## 1. Visión general

Campus Locator es una app Android para **personas con discapacidad visual** que permite:

1. **Ubicarse** dentro del campus (*"¿dónde estoy?"*).
2. **Ser guiado por voz** hasta un lugar del campus (*"quiero ir a…"*).
3. (Admin) **Construir el dataset** de imágenes de referencia que hace posible lo anterior.
4. (Admin) **Editar el mapa** (capa de alertas sobre el mapa de OpenStreetMap) agregando
   **alertas de obstáculo** con un mensaje que se le leerá al usuario ciego cuando se acerque.

Es **una sola app / un solo APK**. La interfaz de administración se habilita únicamente
cuando el usuario inicia sesión con rol `ADMIN`.

### Principios de diseño (aplican a TODAS las vistas públicas)

- **Voz primero:** toda acción importante debe poder hacerse por voz; la pantalla es un
  apoyo, no el medio principal.
- **Accesibilidad:** compatible con TalkBack, `contentDescription` en todo elemento,
  orden de foco lógico, áreas táctiles grandes (mínimo 56–64 dp), alto contraste, texto
  escalable.
- **Pocas acciones por pantalla:** botones muy grandes, poco texto, sin gestos complejos.
- **Retroalimentación multimodal:** cada evento relevante se anuncia por voz, vibración
  y, para quien ve, visualmente.
- **El usuario nunca opera la cámara:** la captura es automática.

---

## 2. Funcionalidades en detalle

### 2.1 Ubicarse (comando "uno")

1. En Inicio, el usuario dice *"uno"* (o toca el botón).
2. La app le indica por voz: *"Sostén el celular al frente y da una vuelta completa
   lentamente."*
3. La app abre la cámara trasera y usa el sensor de orientación (rotation vector) para
   saber cuánto ha girado. **Captura 5 fotos automáticamente**, una cada ~72° a lo largo
   de los 360° (0°, 72°, 144°, 216°, 288°). Cada foto se guarda junto con su `heading`
   (orientación).
4. Se envían las 5 fotos (+ headings) al backend.
5. El backend genera embeddings DINOv2, los compara con el dataset y devuelve la posición
   estimada (x, y), la orientación probable y un nivel de confianza.
6. La app anuncia por voz el resultado y lo muestra en el mapa.

Casos especiales: usuario gira muy rápido (se le pide ir más lento), foto borrosa o
oscura (se repite esa captura), baja confianza (se pide repetir la vuelta), sin conexión.

> Nota: el control de calidad (foto borrosa/oscura) está **desactivado temporalmente**; ver 6.2.

### 2.2 Ir a un lugar (comando "dos")

1. El usuario dice *"dos"* y después **el nombre del destino** (reconocimiento de voz,
   con coincidencia aproximada contra la lista de lugares y confirmación por voz).
2. Se ejecuta primero el proceso de **2.1** para ubicar al usuario.
3. Se calcula la ruta sobre el grafo de caminos del campus.
4. **Guiado por voz** en tiempo real: *"sigue recto 20 metros"*, *"gira a la izquierda"*,
   *"has llegado"*. Se anuncian también las **alertas de obstáculo cercanas** definidas
   por el admin en el mapa (ver 2.5).
5. Durante el trayecto se mantiene la posición con el sistema híbrido (2.3).
6. Si el usuario se desvía, se **recalcula la ruta** y se avisa.

### 2.3 Seguimiento de posición (sistema híbrido)

Dos sistemas trabajan en paralelo y se fusionan:

| Sistema | Qué usa | Qué aporta | Limitación |
|---|---|---|---|
| **Navegación inercial (PDR)** | Detector de pasos, acelerómetro, giroscopio, rotation vector/magnetómetro, longitud de paso calibrada por dispositivo (7.3b) | Posición continua y en tiempo real, sin red | El error se **acumula** con el tiempo |
| **Corrección visual** | Foto automática periódica → backend → embedding → posición | Posición absoluta que **corrige el error acumulado** | Latencia, depende de red y de buena imagen |

**Fusión:** la posición PDR avanza en cada paso. Cuando llega una posición visual con
buena confianza, se corrige la posición actual (filtro de Kalman o filtro de partículas,
con la posición PDR como predicción y la visual como medición). La captura visual se
dispara **automáticamente** por tiempo (ej. cada N segundos), por distancia recorrida, o
cuando la incertidumbre estimada supera un umbral. **Sin intervención del usuario.**

> **Estado de implementación (2026-10-10):** el sistema inercial (PDR) ya existe en Kotlin y es el
> **único** sitio que calcula la posición: `sensors/PdrEngine.kt` (lógica pura),
> `sensors/StepDetector.kt` (pasos por acelerómetro) y `sensors/PdrTracker.kt` (sensores de Android).
> La posición sale de **pasos × longitud de paso** en la dirección del rumbo (la longitud es la **calibrada
> por el admin en 7.3b**, o 0,72 m por defecto si nunca se calibró): la
> velocidad y la aceleración **no** influyen en ella (la velocidad solo se muestra y la aceleración
> detecta los pasos y dibuja una gráfica). **Los pasos salen siempre del acelerómetro** (desde 2026-10-12):
> el sensor de hardware `TYPE_STEP_DETECTOR` se descartó porque tardaba 1–3 s en reaccionar y hacía lentas la
> calibración (7.3b) y la recolección (7.4); con el acelerómetro el primer paso se cuenta en ~0,1 s. La **corrección visual**
> y la **fusión** (`domain/fusion/`) todavía no existen. Detalle en 11.2.

### 2.4 Recolección del dataset (admin)

El dataset es la base del sistema: **cada registro = foto + embedding DINOv2 + coordenada
(+ orientación)**.

1. El admin inicia sesión y entra a "Recolector".
2. **Se ubica manualmente en el mapa** (toca el punto donde está parado, y fija hacia
   dónde mira). Esa es la coordenada inicial exacta.
3. Empieza la grabación de un nuevo **"video"** (ver concepto abajo) y **camina por el campus**. La app usa el mismo sistema inercial (PDR)
   para ir actualizando su coordenada, y **captura fotos automáticamente** (por tiempo y/o
   distancia), guardando cada una con su coordenada estimada y orientación.
4. Puede **reubicarse manualmente** (re-anclar) al pasar por puntos conocidos para
   corregir el error acumulado (ya que aquí no hay dataset previo contra el cual
   corregirse, o bien se corrige contra el dataset ya existente cuando lo hay).
5. Mientras camina puede **agregar alertas de obstáculo en su posición actual** con un
   botón (escribe o dicta el mensaje), sin tener que ir luego al editor de mapa.
6. Al finalizar el video, se sube al backend: se almacenan las fotos, se generan los
   embeddings con DINOv2 y se indexan.

#### El concepto de "video" (recorrido de recolección)

Cada vez que el recolector se ubica en el mapa y empieza a caminar se crea un **video**
(ej. `video1`, `video2`…). **El video como tal no se guarda**: es solo un **identificador
lógico que agrupa todas las fotos tomadas durante ese recorrido**, que están relacionadas
entre sí porque pertenecen a la misma caminata continua.

- Cada foto del dataset guarda su `video_id`: `foto + embedding + coordenada + orientación + video_id`.
- Un video tiene: nombre (autonumerado, **renombrable**, ej. "video1" → "Entrada norte"),
  fecha/hora, duración, distancia, punto de inicio, nº de fotos y estado.
- **Ver un video en el mapa:** al seleccionar un video, el recolector ve en el mapa
  **SOLO las fotos de ese video** (marcadores con su orientación y la trayectoria),
  ocultando las de los demás videos.
- **Eliminar un video:** borra **el video y todas sus fotos** (archivos de imagen,
  embeddings y entradas del índice de búsqueda). Es una acción destructiva e irreversible
  que **cambia de inmediato los resultados de ubicación** del flujo público, por lo que
  exige confirmación explícita (ver vista 7.14).
- Las **alertas de obstáculo** creadas durante un video son **independientes**: borrar el
  video **no** borra esas alertas.
- Reubicarse manualmente (re-anclar) durante la grabación **no crea otro video**: se
  mantiene el mismo video y se corrigen las coordenadas de las fotos afectadas.

### 2.5 Obstáculos y alertas en el mapa

Los obstáculos **no se detectan con la cámara**: son **puntos de alerta que el
recolector/admin coloca manualmente en el mapa** y que el sistema usa para avisarle al
usuario ciego cuando está cerca.

**Qué es una alerta:**

| Campo | Descripción |
|---|---|
| Coordenada | Punto en el mapa donde está el obstáculo o la zona de cuidado |
| **Mensaje** | Texto libre escrito por el admin, que se leerá tal cual al usuario. Ej.: *"Ten cuidado, hay un lago alrededor de la biblioteca"* o *"Ten cuidado, hay bancas cerca, no te vayas a estrellar"* |
| Radio de activación | Distancia (m) a la que se dispara el aviso (ej. 15 m) |
| Tipo (opcional) | Agua, mobiliario, escalones, obra, vehículos, otro (solo para organizar/filtrar y para el ícono) |
| Prioridad | Normal / Alta (las altas interrumpen otras instrucciones de voz) |
| Estado | Activa / Inactiva (permite desactivar sin borrar, ej. obras temporales) |
| Vigencia (opcional) | Fecha de inicio/fin para obstáculos temporales |

**Cómo funciona en el flujo público:**
- La app descarga las alertas y las **guarda en local** para que funcionen sin conexión.
- Durante la **navegación guiada** (y opcionalmente al mostrar el resultado de ubicación),
  se compara la posición estimada del usuario con las alertas: si entra al radio de una
  alerta (sumando la incertidumbre actual de la posición), la app **lee el mensaje por voz**
  y vibra.
- Cada alerta se anuncia **una sola vez por aproximación** (con un tiempo de espera antes de
  repetirse) para no saturar al usuario.
- Las alertas de prioridad alta **interrumpen** la instrucción de voz en curso.
- Se priorizan las alertas que están **en la ruta** o cerca de ella.

**Cómo las crea el admin:** desde el **Editor de mapa y alertas** (vista 15) o desde la
vista de **Recolección en curso** con el botón "Agregar alerta aquí" (ver sección 7).

> Importante: las alertas son una **capa propia** que se dibuja encima del mapa base de
> OpenStreetMap (como capa de Leaflet) y se guarda en el backend; **el mapa base nunca se
> modifica**.

### 2.6 Mapa del campus (OpenStreetMap + Leaflet)

> **Decisión de arquitectura:** el archivo `eafit.mbtiles` **se descartó** porque no fue
> posible implementarlo. El mapa ahora se carga **directamente desde internet** desde
> OpenStreetMap, y se dibuja con **Leaflet** dentro de un `WebView`. Ya no hay un archivo de
> mapa dentro de la app ni un endpoint para versionarlo.

- **Mapa base:** teselas raster de OpenStreetMap, con la URL
  `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` (zoom máximo 19). Se muestra la
  atribución *© OpenStreetMap* (obligatoria; ya está en `app.js`).
- **Render:** Leaflet 1.9.4, en la página web `index.html` + `app.js` ("StepTracker"), que
  se incluye en la app como assets (`app/src/main/assets/`) y se carga en un `WebView`.
- **Coordenadas:** el sistema completo (posición del usuario, fotos del dataset, lugares,
  alertas) usa **latitud / longitud** (WGS84). Leaflet se encarga de la proyección Web
  Mercator de las teselas.
- **Capas** que se dibujan sobre el mapa base: posición y orientación del usuario, punto de
  inicio, trayectoria recorrida y, a medida que se implementen, ruta, lugares de interés,
  **alertas de obstáculo** y, solo para el admin, cobertura de fotos.
- Para el admin, "modificar el mapa" significa editar estas capas (alertas y lugares).
- **Requiere conexión para el mapa base.** Sin red, las teselas que el `WebView` ya
  guardó en caché se siguen viendo y el PDR sigue calculando la posición, pero las zonas no
  visitadas antes aparecen en blanco. Las alertas y la voz funcionan sin red porque no
  dependen de las teselas (alertas en caché local, ver 2.5).

#### Qué implementa hoy `app.js` (StepTracker)

| Función | Detalle |
|---|---|
| Posición inicial | Toque en el mapa (solo si no se está rastreando) o botón GPS (`navigator.geolocation`). Al abrir, intenta usar el GPS automáticamente |
| Seguimiento por pasos (PDR) | **Ya no lo calcula la página.** Kotlin (`PdrEngine`) avanza una longitud de paso (la calibrada en 7.3b, o 0,72 m por defecto) por paso en la dirección del rumbo y envía la posición con `onNativePosition`; la página mueve el marcador, dibuja la trayectoria y calcula las estadísticas de pantalla (cadencia, calorías) |
| Rumbo | El promedio circular de las últimas 6 lecturas lo hace Kotlin (`PdrEngine`); la página solo suaviza la flecha del marcador con un filtro adaptativo. Si Kotlin avisa que no hay brújula (`onNativeBrujula(false)`), aparece una **rueda manual de rumbo** que envía `setManualHeading` |
| Trayectoria | Polilínea punteada con todos los puntos recorridos; botón de reinicio que vuelve al punto inicial |
| Panel de estadísticas | Pasos, velocidad, aceleración (con gráfica en vivo), distancia, cadencia, rumbo, calorías y coordenadas |
| Brújula | Widget con rosa de los vientos y orientación cardinal |
| Centrar | Botón que centra el mapa en la posición actual |

#### Puente WebView ↔ Android (`AndroidBridge`)

En Android **toda la lógica de pasos, rumbo y posición vive en Kotlin** (`sensors/PdrEngine`, ver
2.3 y 11.2). La página solo pide arrancar y parar, le avisa a Kotlin lo que el usuario toca (punto de
partida, rumbo manual, reinicio) y **dibuja** lo que Kotlin le envía. Ya **no hay sensores web de
respaldo** (`devicemotion` / `deviceorientation`): si la página no encuentra `window.AndroidBridge`
(navegador o iOS) el mapa se ve, pero **el seguimiento no funciona**; al pulsar ▶ avisa «El
seguimiento solo funciona dentro de la app».

| Dirección | Función | Descripción |
|---|---|---|
| Web → Kotlin | `AndroidBridge.startSensors()` | Empieza a leer pasos, aceleración y rumbo |
| Web → Kotlin | `AndroidBridge.stopSensors()` | Detiene los sensores |
| Web → Kotlin | `AndroidBridge.setPosition(lat, lng)` | Punto de partida (toque en el mapa o GPS) |
| Web → Kotlin | `AndroidBridge.setManualHeading(grados)` | Rumbo de la rueda manual (solo si no hay brújula) |
| Web → Kotlin | `AndroidBridge.reset()` | Vuelve al punto de partida con los pasos en cero |
| Kotlin → Web | `window.onNativePosition(lat, lng, pasos, distanciaM, velocidadMps)` | Posición calculada tras cada paso (y al fijar o reiniciar). Con `pasos = 0` no se suma punto a la trayectoria |
| Kotlin → Web | `window.onNativeHeading(grados)` | Rumbo 0–360, norte real, ya promediado (~20 Hz, solo con el seguimiento activo) |
| Kotlin → Web | `window.onNativeAccel(desviacion)` | Desviación de la aceleración respecto a la gravedad (m/s²), solo para la gráfica |
| Kotlin → Web | `window.onNativeBrujula(disponible)` | Se envía en cada `startSensors()`; si es `false` aparece la rueda manual |
| Kotlin → Web | `window.onNativeStepUnavailable(motivo)` | El teléfono no tiene acelerómetro (`'no_sensor'`); solo muestra un aviso. Ya no se envía `'permission_denied'` (el acelerómetro no necesita permiso) |

Se eliminaron `onNativeStep(count)` y la firma anterior `onNativeAccel(x, y, z)`.

Requisitos del lado Kotlin (`map/MapaPublicoScreen.kt` y `map/PuentePdr.kt`): JavaScript activado en
el `WebView`, `addJavascriptInterface(PuentePdr(tracker), "AndroidBridge")` y llamar a las funciones
`window.onNative*` con `evaluateJavascript` **desde el hilo principal**. Los métodos
`@JavascriptInterface` llegan en un hilo del `WebView`, así que `PuentePdr` los reenvía al hilo
principal, que es donde vive `PdrTracker`. El mapa se carga con `file:///android_asset/index.html`.

### 2.7 Interacción por voz

- **Entrada:** `SpeechRecognizer` de Android (comandos "uno", "dos", nombres de lugares,
  "sí/no", "repetir", "cancelar", "ayuda").
- **Salida:** `TextToSpeech`, con cola de prioridades (una alerta de obstáculo de prioridad
  alta interrumpe a una instrucción normal).
- Todo comando de voz tiene un **equivalente táctil** y es compatible con TalkBack.

---

## 3. Arquitectura del sistema

```
┌────────────────────────── App Android ──────────────────────────┐
│  UI (Compose)  →  ViewModels  →  Domain (casos de uso)          │
│                                      │                          │
│              ┌───────────────────────┼───────────────────────┐  │
│              ▼                       ▼                       ▼  │
│        Sensores / PDR          Cámara (CameraX)        Voz (TTS/STT)
│              │                       │                          │
│              └──────────► Data (repositorios) ◄─────────────────┘
└─────────────────────────────────┬───────────────────────────────┘
                                  │ HTTPS (ApiConfig.kt)
┌─────────────────────────────────▼───────────────────────────────┐
│                          Backend                                │
│  API REST → DINOv2 (embeddings) → Búsqueda por similitud        │
│  (índice vectorial) → Dataset: foto + embedding + coordenada    │
│  Auth/roles · Lugares · Alertas · Grafo de caminos · Estadísticas│
└─────────────────────────────────────────────────────────────────┘
```

**El mapa** no pasa por el backend: el `WebView` de la app (Leaflet) pide las teselas
**directamente a OpenStreetMap** por internet.

```
┌──────────── WebView (index.html + app.js · Leaflet) ───────────┐
│  Mapa · marcador · trayectoria · capas (alertas, lugares, ...) │
└───────┬───────────────────────────────────────────────▲────────┘
        │ HTTPS (teselas)                  AndroidBridge │ (sensores, pasos, rumbo)
        ▼                                                │
 tile.openstreetmap.org                       Kotlin: sensors/ (PDR)
```

### Responsabilidades del backend (resumen de endpoints)

| Endpoint (propuesto) | Quién lo usa | Función |
|---|---|---|
| `POST /localize` | Público | Recibe 1–5 fotos (+ headings), devuelve posición, orientación y confianza |
| `POST /localize/frame` | Público | Corrección visual durante la navegación (1 foto) |
| `GET /places` | Público | Lista de lugares/destinos |
| `GET /alerts` | Público | Alertas de obstáculo activas (se cachean en el dispositivo) |
| `GET /route?from&to` | Público | Ruta entre dos coordenadas (o se calcula en el dispositivo) |
| `POST /auth/login` | Todos | Inicio de sesión, devuelve token + rol |
| `POST /collect/videos` | Admin | Crea un video (recorrido) y devuelve su `video_id` |
| `POST /collect/videos/{id}/images` | Admin | Sube fotos del video con coordenada y orientación |
| `GET /admin/videos` | Admin | Lista de videos con resumen (nº de fotos, fecha, estado) |
| `GET /admin/videos/{id}/images` | Admin | Fotos de un solo video (para verlas en el mapa) |
| `PATCH /admin/videos/{id}` | Admin | Renombrar el video |
| `DELETE /admin/videos/{id}` | Admin | Elimina el video y **todas** sus fotos, embeddings y entradas del índice |
| `GET/POST/PUT/DELETE /admin/places` | Admin | CRUD de lugares |
| `GET/POST/PUT/DELETE /admin/alerts` | Admin | CRUD de alertas de obstáculo |
| `GET /admin/images` | Admin | Galería con filtros (incluye filtro por `video_id`) |
| `GET /admin/stats` | Admin | Estadísticas de uso |

---

## 4. Estructura de paquetes

```
com.example.myapplication/
├── MainActivity.kt              # Actividad única, aloja el NavHost y pide los permisos
├── MyApp.kt                     # Application: inicia el registro (AppLog) y captura crashes
├── ApiConfig.kt                 # URL base y configuración del backend
├── logs/                        # AppLog: registro de eventos en Logcat y en archivo
│
├── ui/                          # Capa de presentación (Compose)
│   ├── navigation/              # NavHost, rutas, guardas por rol
│   ├── theme/                   # Colores (alto contraste), tipografía, formas
│   ├── components/              # Componentes reutilizables
│   ├── inicio/
│   ├── ubicacion/
│   ├── destino/
│   ├── navegacion/
│   ├── ajustes/
│   ├── auth/
│   └── admin/
│       ├── panel/
│       ├── recoleccion/     # 7.3 ubicación manual y 7.4 recolección en curso (7.5 pendiente)
│       ├── calibracion/     # 7.3b calibración de la longitud de paso
│       ├── lugares/
│       ├── mapa/            # Editor de mapa y alertas
│       ├── imagenes/
│       ├── videos/          # Lista y detalle de videos de recolección
│       └── estadisticas/
│
├── domain/                      # Lógica de negocio pura (sin Android)
│   ├── model/                   # Posicion, Lugar, Alerta, Ruta, Video, Foto, Usuario...
│   ├── usecase/                 # UbicarUsuario, CalcularRuta, IniciarRecoleccion, DetectarAlertasCercanas...
│   └── fusion/                  # Fusión PDR + posición visual (Kalman/partículas)
│
├── data/                        # Acceso a datos
│   ├── remote/                  # Retrofit/Ktor, DTOs, API
│   ├── repository/              # Implementaciones de repositorios
│   └── local/                   # Caché local (Room/DataStore), cola de subida offline
│
├── sensors/                     # Sensores y PDR
│   ├── PdrEngine, StepDetector, PdrTracker, OrientationProvider
│
├── camera/                      # CameraX, captura automática (una carpeta por escaneo), calidad de imagen (sin uso por ahora)
├── map/                         # WebView del mapa Leaflet/OSM, AndroidBridge y datos de capas (usuario, ruta, lugares, alertas). Hoy: MapaPublicoScreen, PuentePdr y MapaWebView (fábrica común de los WebView de mapa, 11.9)
├── voice/                       # Wrappers de TextToSpeech y SpeechRecognizer
└── session/                     # Sesión, token, rol (USER / ADMIN)
```

> Fuera del código Kotlin, el mapa vive en `app/src/main/assets/`: `index.html` y `app.js`
> (Leaflet + OpenStreetMap, ver 2.6), las páginas del editor, del detalle de video y de la ubicación manual (`ubicacion_manual.html/js`), y la base común `mapa_base.js` (11.9).

> Actualmente en el repo existen `ui/`, `camera/`, `sensors/`, `map/`, `logs/`, `session/`,
> `data/repository/`, `domain/model/`, `domain/usecase/`, `ApiConfig.kt`, `MyApp.kt` y
> `MainActivity.kt`; el resto (`domain/fusion/`, `data/remote/`, `data/local/`, `voice/`,
> `ui/navigation/`) se crea a medida que se implementa. ⚠ Dentro del paquete Kotlin hay archivos que
> no son código de la app (`archivos_zip.py`, `crear_archivos.py`, `out.zip`): sacarlos (ver 9).

### Navegación y roles

- Un único `NavHost`. ⚠ **Hoy vive en `MainActivity.kt` (composable `AppNav`)**, no en
  `ui/navigation/AppNavHost.kt` como se planeó; ver 11.8.
- Rutas públicas: Inicio, Ubicación, Destino, Navegación, Ajustes, Login.
- Rutas `admin/*` protegidas: si no hay sesión con rol `ADMIN` se redirige a Login. ⚠ **Hoy `AppNav`
  no aplica esa protección a nivel de ruta**; solo el panel dispara `onSinSesion` (ver 11.8).
- El acceso a Login desde Inicio debe ser discreto (el usuario final casi nunca lo usa),
  pero accesible para TalkBack.

### Permisos de Android

| Permiso | Para qué | Tipo |
|---|---|---|
| `INTERNET` | Llamadas al backend y descarga de teselas de OpenStreetMap en el `WebView` | Normal |
| `ACCESS_NETWORK_STATE` | Indicador y aviso de pérdida de conexión | Normal |
| `CAMERA` | Escaneo 360°, corrección visual y recolección | Diálogo |
| `RECORD_AUDIO` | `SpeechRecognizer` (comandos y dictado) | Diálogo |
| `ACTIVITY_RECOGNITION` | **Ya no lo necesita el PDR** (los pasos salen del acelerómetro desde 2026-10-12). Hoy `Permisos.INICIALES` y `Permisos.ACTIVIDAD` lo siguen pidiendo sin efecto: quitarlo de ambos y del Manifest cuando se limpie `MainActivity` | Diálogo |
| `VIBRATE` | Vibración al capturar, girar y alertar | Normal |
| `ACCESS_FINE_LOCATION` | **Opcional.** Solo si se mantiene el botón GPS del mapa web (posición inicial). Requiere también atender los permisos de geolocalización del `WebView` | Diálogo |

No requieren permiso: acelerómetro, giroscopio, magnetómetro, rotation vector, almacenamiento
privado de la app, `keepScreenOn`. La ubicación del usuario **no depende del GPS** (se calcula con
PDR + fotos); el GPS solo es una ayuda opcional para fijar el punto inicial. No se usa
almacenamiento externo.

**Flujo de solicitud (`MainActivity.kt`):**
- **Inicio:** pide cámara, micrófono y actividad física en un solo diálogo del sistema. Inicio
  se muestra aunque se niegue alguno (queda la opción táctil).
- **Ubicarme:** vuelve a comprobar la cámara (indispensable). Si se niega, regresa a Inicio.
- Las pantallas de recolección y navegación deberán usar el mismo `PedirPermisos`.
- **Calibración (7.3b):** la ruta `admin/calibracion` aún pide `Permisos.ACTIVIDAD`, pero ya no hace falta: los pasos salen del acelerómetro, que no requiere permiso (negarlo no cambia nada).
- Si se niega el micrófono: solo botones. La actividad física ya no afecta al PDR; la página solo muestra un aviso
  (`onNativeStepUnavailable`) si el teléfono no tiene acelerómetro.
- El Manifest declara `<queries>` para `RecognitionService` y `TTS_SERVICE` (Android 11+), y
  `uses-feature` con `required="false"` para cámara, micrófono y sensores.

### Registro de eventos (logs) y depuración

- `logs/AppLog.kt` escribe cada mensaje en **Logcat** y en el archivo `files/logs/app.log`
  (rota a ~1 MB y conserva `app.log.1`).
- `MyApp.kt` inicializa `AppLog` al arrancar y registra los crashes no capturados (tag `CRASH`).
  Debe declararse en el Manifest con `android:name=".MyApp"`.
- Cada escaneo abre una sesión (`AppLog.nuevaSesion("scan")`): sus líneas llevan un id como
  `[scan-12345]` para seguir una vuelta completa.
- Tags usados: `App`, `CRASH`, `EscaneoVM`, `Camara`, `DestinoVM`.
- Registrar transiciones y decisiones, **no** cada lectura de sensor (50 por segundo).
- No registrar datos sensibles (tokens, credenciales).

**Cómo consultar:**
- Logcat de Android Studio: filtro `package:mine`, o `tag:EscaneoVM`.
- Archivo de log y fotos: *Device Explorer* → `data/data/com.example.myapplication/files/`
  (`logs/app.log` y `camera/photos/`), o con `adb exec-out run-as com.example.myapplication`.

---

## 5. Mapa de vistas

| # | Vista | Archivo | Flujo |
|---|---|---|---|
| 1 | Inicio | `ui/inicio/InicioScreen.kt` | Público |
| 2 | Ubicarse (escaneo 360°) | `ui/ubicacion/EscaneoScreen.kt` | Público |
| 3 | Resultado de ubicación | `ui/ubicacion/ResultadoUbicacionScreen.kt` | Público |
| 4 | Selección de destino | `ui/destino/SeleccionDestinoScreen.kt` | Público |
| 5 | Navegación guiada | `ui/navegacion/NavegacionScreen.kt` | Público |
| 6 | Llegada | `ui/navegacion/LlegadaScreen.kt` | Público |
| 7 | Ajustes | `ui/ajustes/AjustesScreen.kt` | Público |
| 8 | Login | `ui/auth/LoginScreen.kt` | Admin |
| 9 | Panel admin | `ui/admin/panel/PanelAdminScreen.kt` | Admin |
| 10 | Ubicación manual inicial | `ui/admin/recoleccion/UbicacionManualScreen.kt` | Admin |
| 10b | Calibración de la longitud de paso | `ui/admin/calibracion/CalibracionScreen.kt` | Admin |
| 11 | Recolección en curso | `ui/admin/recoleccion/RecoleccionScreen.kt` | Admin |
| 12 | Resumen de video | `ui/admin/recoleccion/ResumenVideoScreen.kt` | Admin |
| 13 | Lista de lugares | `ui/admin/lugares/LugaresScreen.kt` | Admin |
| 14 | Formulario de lugar | `ui/admin/lugares/LugarFormScreen.kt` | Admin |
| 15 | Editor de mapa y alertas | `ui/admin/mapa/EditorMapaScreen.kt` | Admin |
| 16 | Formulario de alerta | `ui/admin/mapa/AlertaFormSheet.kt` | Admin |
| 17 | Lista de alertas | `ui/admin/mapa/AlertasScreen.kt` | Admin |
| 18 | Galería de imágenes | `ui/admin/imagenes/GaleriaScreen.kt` | Admin |
| 19 | Detalle de imagen | `ui/admin/imagenes/DetalleImagenScreen.kt` | Admin |
| 20 | Lista de videos | `ui/admin/videos/VideosScreen.kt` | Admin |
| 21 | Detalle de video (mapa + eliminar) | `ui/admin/videos/VideoDetalleScreen.kt` | Admin |
| 22 | Estadísticas | `ui/admin/estadisticas/EstadisticasScreen.kt` | Admin |

Componentes compartidos en `ui/components/`: `BotonGrande.kt`, `MapaCampus.kt`, `MarcadorAlerta.kt`,
`IndicadorVoz.kt`, `BannerEstado.kt`, `DialogoConfirmacion.kt`, `TopBarAccesible.kt`.

---

## 6. Especificación de vistas públicas

> Para todas: alto contraste, textos grandes, botones de mínimo 64 dp, `contentDescription`
> completo, y cada mensaje importante se lee en voz alta automáticamente.

### 6.1 Inicio — `ui/inicio/InicioScreen.kt`

![alt text](<assets/inicio.png>)

**Propósito:** punto de entrada. Permite elegir entre ubicarse o ir a un lugar.

**Elementos:**
- Título de la app y mensaje de bienvenida (se lee por voz al abrir): *"Di uno para saber
  dónde estás, o dos para ir a un lugar."*
- **Botón grande 1: "Ubicarme"** (ocupa ~40 % de la pantalla). Acción: iniciar flujo 2.1.
- **Botón grande 2: "Ir a un lugar"** (ocupa ~40 % de la pantalla). Acción: abrir selección
  de destino.
- **Indicador de escucha por voz** (micrófono animado + texto "Te escucho…") que muestra
  cuando la app está atenta al comando.
- Botón de **micrófono** para activar/reactivar la escucha manualmente.
- Botón pequeño de **Ajustes** (esquina).
- Acceso discreto a **"Acceso administrador"** (texto pequeño/ícono) que lleva a Login.
- Indicador de **estado de conexión** con el backend.

**Comportamiento:**
- Al abrir, lee las instrucciones y empieza a escuchar.
- Reconoce "uno", "dos" y sinónimos ("ubicarme", "ir a").
- Si no entiende, repite las opciones.
- Pide los permisos (cámara, micrófono, actividad física) en un único diálogo del sistema la
  primera vez. *Pendiente:* la explicación hablada previa al diálogo.

---

### 6.2 Ubicarse (escaneo 360°) — `ui/ubicacion/EscaneoScreen.kt`

![alt text](<assets/ubicarse.png>)

**Propósito:** guiar al usuario para dar la vuelta completa mientras la app captura
5 fotos automáticamente.

**Elementos:**
- **Vista previa de la cámara** (apoyo visual para quien ve; el usuario no la necesita).
- **Indicador circular de progreso de giro** (anillo de 0° a 360°) con 5 marcas que se
  llenan al capturar cada foto.
- **Contador de fotos**: "Foto 2 de 5".
- **Texto de instrucción grande**: "Gira lentamente hacia la derecha", "Más despacio",
  "Mantén el celular vertical".
- **Indicador de inclinación del teléfono** (si no está vertical, avisa).
- Botón **"Cancelar"** (grande, siempre visible).
- Botón **"Repetir"** (aparece si falla). Abre una carpeta de escaneo nueva.
- Animación/estado de **"Analizando…"** tras la quinta foto, mientras se espera al backend.

**Comportamiento:**
- Instrucciones por voz al entrar. Un sonido/vibración corto confirma cada captura.
- Se captura automáticamente según los grados girados (rotation vector), una foto cada 72°.
- Avisos hablados si gira demasiado rápido o si el celular no está vertical.
- **Control de calidad: desactivado temporalmente.** Toda foto que CameraX guarda se acepta;
  no se emiten avisos de imagen borrosa/oscura. `camera/CalidadImagen.kt` se conserva sin
  usar, para reactivarlo más adelante.
- Al completar la vuelta, avisa *"Listo, analizando"* y navega a Resultado.
- Estados de error: sin conexión, tiempo agotado, vuelta incompleta.

**Almacenamiento de las fotos:**
- Cada escaneo crea su propia carpeta, nombrada con la fecha y hora de inicio:
  `files/camera/photos/<yyyy-MM-dd_HH-mm-ss>/` (almacenamiento privado de la app).
- Dentro: `escaneo_1.jpg` … `escaneo_5.jpg`.
- Se conservan solo los **20 escaneos más recientes**; los más antiguos se borran al crear
  una carpeta nueva (`crearCarpetaEscaneo`).
- La constante `CONSERVAR_FOTOS` (en `EscaneoViewModel.kt`) decide si las fotos se borran al
  cancelar, repetir o salir de la pantalla. Hoy está en `true` (no se borran) para depurar.
  **Debe ponerse en `false` antes de publicar** (ver decisión abierta 12).
- Para verlas: Device Explorer de Android Studio o `adb` (ver "Registro de eventos (logs) y
  depuración", en la sección 4).

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/ubicacion/EscaneoScreen.kt` | Pantalla: conecta permisos, sensor, cámara, carpeta del escaneo y ViewModel |
| `ui/ubicacion/EscaneoViewModel.kt` | Lógica del giro, disparo de fotos y backend (sin control de calidad por ahora) |
| `ui/ubicacion/EscaneoState.kt` | Estado (`EscaneoUiState`) y eventos (`EscaneoEvento`) |
| `ui/ubicacion/EscaneoConfig.kt` | Parámetros ajustables y paleta |
| `ui/ubicacion/EscaneoBackend.kt` | Contrato con el backend (stub temporal) |
| `ui/ubicacion/FeedbackCaptura.kt` | Vibración y sonido de confirmación |
| `ui/ubicacion/componentes/` | `VistaCamara`, `AnilloProgreso`, `PanelesEscaneo` |
| `camera/CapturaFoto.kt` | Captura automática y creación de la carpeta de cada escaneo |
| `camera/CalidadImagen.kt` | Control de calidad (**sin uso por ahora**) |
| `sensors/OrientationProvider.kt` | Acimut y cabeceo del rotation vector |
| `logs/AppLog.kt` | Registro de eventos (ver sección 4) |

---

### 6.3 Resultado de ubicación — `ui/ubicacion/ResultadoUbicacionScreen.kt`

![alt text](<assets/resultados_de_ubicacion.png>)

**Propósito:** informar dónde está el usuario y qué hacer después.

**Elementos:**
- **Texto principal grande** con la ubicación: *"Estás cerca de la biblioteca"*.
- **Descripción de referencias**: *"El bloque de los trillizos está a tu derecha"*.
- **Mapa del campus** con el punto del usuario, flecha de orientación y puntos de interés
  cercanos.
- **Indicador de confianza** (alta/media/baja) en texto simple.
- **Alertas cercanas** (si hay alguna dentro del radio): se muestran y se leen después de la ubicación, ej. *"Ten cuidado, hay un lago alrededor de la biblioteca"*.
- Botón **"Repetir en voz alta"**.
- Botón **"Ir a un lugar desde aquí"** (→ Selección de destino, con posición ya fijada).
- Botón **"Volver a ubicarme"** (si la confianza es baja o el usuario no está de acuerdo).
- Botón **"Volver al inicio"**.

**Comportamiento:** lee el resultado automáticamente. Si la confianza es baja, lo dice y
sugiere repetir la vuelta. Cuando esta vista se usa como paso previo a la navegación, tras
confirmar avanza automáticamente a la guía.

---

### 6.4 Selección de destino — `ui/destino/SeleccionDestinoScreen.kt`

![alt text](<assets/seleccion_de_destino.png>)

**Propósito:** elegir el lugar al que se quiere ir.

**Elementos:**
- Pregunta hablada y escrita: *"¿A dónde quieres ir?"*
- **Botón de micrófono grande** para dictar el destino.
- **Texto reconocido** mostrado en pantalla.
- **Diálogo de confirmación**: *"¿Quieres ir a la biblioteca? Di sí o no."* con botones
  Sí / No grandes.
- **Lista de lugares** (alternativa táctil): buscador + lista con nombre y categoría,
  ordenada por cercanía/popularidad.
- **Chips de categorías** (biblioteca, cafetería, baños, bloques…).
- Botón **Volver**.

**Comportamiento:** coincidencia aproximada con los nombres de lugares; si hay varias
coincidencias, las lee y pide elegir. Tras confirmar, si aún no hay ubicación vigente,
lanza el escaneo 360° y luego la navegación.

**Estado de implementación:** implementada con una lista de lugares de prueba (stub). Falta el
backend real (`GET /places`) con distancias, fotos de los lugares (hoy se muestra el ícono de la
categoría si no hay `imagenUrl`), ordenar por popularidad y pasar el destino a la vista 6.5.

**Voz:** usa el mismo `VoiceController` de Inicio y Escaneo. Si se negó el micrófono, la vista
funciona solo con toques y muestra un aviso. Tocar, pausar o salir invalida el flujo hablado en
curso (ver patrón de token en 11.2).

**Varias coincidencias:** si lo dicho se parece a 2 o 3 lugares, se leen y se muestran como botones
para elegir.

**Navegación:** al confirmar emite `DestinoEvento.Confirmado(lugar)`. Hoy `AppNav` abre `ubicarme`
(**TODO:** pasar el destino y abrir la vista 6.5 tras el escaneo; ver decisión abierta 15).

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/destino/SeleccionDestinoScreen.kt` | Pantalla (`SeleccionDestinoScreen`: permiso de micrófono, ciclo de vida, navegación), contenido sin estado (`SeleccionDestinoContent`), `DestinoAcciones` y preview |
| `ui/destino/SeleccionDestinoViewModel.kt` | Flujo hablado (preguntar → escuchar → confirmar sí/no), búsqueda, filtros y orden |
| `ui/destino/SeleccionDestinoState.kt` | Estado (`DestinoUiState`), `OrdenLugares`, `ErrorDestino` y evento `DestinoEvento.Confirmado` |
| `ui/destino/componentes/` | `PanelesVoz` (barra, micrófono, texto reconocido, confirmación, opciones), `ListaLugares` (chips, buscador, lista, botón Volver) y `Comun` (tarjeta, íconos por categoría) |
| `domain/usecase/BuscarLugares.kt` | Coincidencia aproximada, filtro del buscador e interpretación de "sí" / "no" |
| `domain/model/LugarDestino.kt` | `LugarDestino` y `CategoriaLugar` |
| `data/repository/LugaresRepository.kt` | Contrato (`GET /places`) y stub temporal (**TODO:** reemplazar por Retrofit/Ktor con `ApiConfig.kt`) |

---

### 6.5 Navegación guiada — `ui/navegacion/NavegacionScreen.kt`

![alt text](<assets/navegacion_guiada.png>)

**Propósito:** guiar en tiempo real hasta el destino.

**Elementos:**
- **Instrucción actual en texto muy grande**: "Sigue recto 20 m", "Gira a la izquierda".
- **Flecha direccional grande** indicando hacia dónde avanzar respecto a la orientación
  actual.
- **Distancia restante** y **tiempo estimado**.
- **Nombre del destino**.
- **Mapa** con ruta, posición actual, orientación y destino (vista de apoyo).
- **Banner de alerta de obstáculo** (ámbar/rojo, alto contraste, aparece sobre todo lo demás)
  con **el mensaje escrito por el admin** y el ícono según el tipo, ej. *"Ten cuidado, hay
  bancas cerca, no te vayas a estrellar"*. Se mantiene visible unos segundos o hasta que el
  usuario se aleje.
- **Marcadores de alertas** en el mapa de apoyo (las cercanas a la ruta).
- Botón **"Repetir alerta"**.
- **Indicador de estado de seguimiento**: precisión estimada y cuándo se hizo la última
  corrección visual (discreto).
- Botón **"Repetir instrucción"** (grande).
- Botón **"Pausar"** / **"Reanudar"**.
- Botón **"Cancelar ruta"** (con confirmación).
- Botón **"No sé dónde estoy / Reubicarme"** (lanza un escaneo 360° nuevo).
- Vista previa de cámara pequeña/oculta (la captura es automática y en segundo plano).

**Comportamiento:**
- Instrucciones por voz y vibración: patrón distinto para izquierda, derecha, giro y
  llegada.
- Posición actualizada por PDR y corregida con fotos automáticas.
- Cuando la posición del usuario entra al radio de una alerta, se lee el mensaje por voz y
  se vibra; las de prioridad alta tienen máxima prioridad en la cola de voz. Cada alerta se
  anuncia una vez por aproximación.
- Recalcula la ruta si el usuario se desvía y lo informa.
- Avisos si hay poca confianza en la posición o pérdida de conexión (continúa con PDR).
- Al llegar, navega a la vista de Llegada.

---

### 6.6 Llegada — `ui/navegacion/LlegadaScreen.kt`

![alt text](<assets/llegada.png>)

**Propósito:** confirmar que se llegó al destino.

**Elementos:**
- Mensaje grande: *"Has llegado a la biblioteca"* (se lee por voz).
- Descripción breve de lo que hay alrededor.
- Botón **"Ir a otro lugar"**.
- Botón **"Volver al inicio"**.
- Pregunta opcional de retroalimentación: *"¿Llegaste bien?"* (Sí / No) para mejorar el
  sistema.

---

### 6.7 Ajustes — `ui/ajustes/AjustesScreen.kt`

![alt text](<assets/ajustes.png>)

**Propósito:** personalizar la experiencia.

**Elementos:**
- **Velocidad de la voz** (slider + botón de prueba).
- **Volumen de avisos / voz**.
- **Intensidad de vibración** (apagada / suave / fuerte).
- **Detalle de las instrucciones** (breve / detallado).
- **Unidad de distancia**: metros / pasos.
- **Anticipación de alertas** (avisar más lejos / más cerca) y opción de repetir alertas ya anunciadas.
- **Idioma de voz**.
- Botón **"Probar voz"**.
- Información de la app / versión.

Todos los controles deben ser operables por TalkBack y con áreas grandes.

---

## 7. Especificación de vistas de administración

> Estas vistas las usa un administrador vidente, por lo que pueden ser más densas
> visualmente, pero deben seguir siendo claras y usables en el celular mientras camina.

### 7.1 Login — `ui/auth/LoginScreen.kt`

![alt text](<assets/login.png>)

**Propósito:** autenticar al administrador para habilitar las vistas `admin/*`.

**Elementos:**
- **Logo** (pin con órbita, dibujado en `Canvas`), nombre "Campus Navi" y lema.
- Campo **correo o usuario**.
- Campo **contraseña** con botón mostrar/ocultar.
- Botón **"Iniciar sesión"** (se deshabilita si hay campos vacíos o mientras carga).
- **Indicador de carga**: "Verificando credenciales…".
- **Mensajes de error** (uno a la vez, con `BannerEstado`):
  - *Credenciales inválidas* (rojo).
  - *Sin conexión* (ámbar).
  - *Sin permisos*, si la cuenta no tiene rol `ADMIN` (rojo).
  - *Algo salió mal*, para errores inesperados (rojo).
- Botón **"Volver al inicio"** al flujo público.

**Comportamiento:**
- Al iniciar sesión se llama a `POST /auth/login` (token + rol).
- **Rol `ADMIN`:** se guarda la sesión y se navega a `admin/panel`, quitando Login de la
  pila de navegación.
- **Rol distinto de `ADMIN`:** se informa que no tiene permisos, **no se guarda la sesión**
  y no se habilita el panel.
- Si al abrir Login ya existe una sesión `ADMIN` guardada, se entra directo al panel. (Solo dentro
  de la misma ejecución: `MyApp` borra la sesión cada vez que la app arranca desde cero; ver 11.3.)
- La sesión se guarda cifrada (`EncryptedSharedPreferences`, llave en Android Keystore).
  `SessionManager.cerrarSesion()` borra token y datos; se invoca desde el botón
  **Cerrar sesión** del Panel admin (vista 7.2).
- No se registran tokens ni credenciales en los logs.
- Al tocar los campos, el error se limpia. Se envía con el botón o con "Listo" del teclado.

**Accesibilidad:** los banners y el indicador de carga son *live regions* (TalkBack los
anuncia al aparecer); el botón de contraseña describe su acción ("Mostrar/Ocultar
contraseña"); botones y campos de 64 dp o más.

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/auth/LoginScreen.kt` | Pantalla (`LoginScreen`) y contenido sin estado (`LoginContent`), con previews |
| `ui/auth/LoginViewModel.kt` | Estado (`LoginUiState`), errores (`LoginError`), evento `IrAlPanel` y lógica del login |
| `ui/components/BannerEstado.kt` | Banner de error/advertencia reutilizable |
| `session/SessionManager.kt` | Sesión cifrada: `guardar`, `obtener`, `esAdmin`, `cerrarSesion` |
| `data/repository/AuthRepository.kt` | Contrato del login (`AuthRepository`) y stub temporal (**TODO:** reemplazar por Retrofit/Ktor con `ApiConfig.kt`) |
| `domain/model/Usuario.kt` | `Rol` (USER/ADMIN), `Usuario`, `Sesion` |

admin@campus.edu.co

**Navegación (`AppNavHost`):**
```kotlin
composable("login") {
    LoginScreen(
        onLoginExitoso = {
            navController.navigate("admin/panel") { popUpTo("login") { inclusive = true } }
        },
        onVolver = { navController.popBackStack() },
    )
}
```
---

### 7.2 Panel admin — `ui/admin/panel/PanelAdminScreen.kt`

![alt text](<assets/panel_admin.png>)

**Propósito:** hub del administrador.

**Elementos:**
- **Encabezado**: avatar, saludo con el primer nombre del admin ("Hola, Alejandro"), rol
  ("Administrador del sistema") y botón de **Ajustes** (esquina superior derecha, lleva a la
  vista pública 6.7).
- **Tarjetas de acceso** (cuadrícula de 2 columnas): **Recolector de imágenes** (destacada),
  **Lugares**, **Mapa y alertas**, **Imágenes**, **Videos**, **Estadísticas**. Cada una muestra
  ícono, título, descripción corta y chevron.
- **Resumen rápido**, con 5 datos:
  - total de fotos del dataset,
  - lugares registrados,
  - alertas activas,
  - último video recolectado (número y fecha/hora, ej. "12 · Hoy, 09:24"),
  - fotos pendientes de subir.
- Chip **"En tiempo real"** (solo aparece cuando el resumen cargó correctamente).
- Botón **Cerrar sesión**.
- Botón **Volver a modo público**.
- Pie con nombre del panel y versión de la app.

**Comportamiento:**
- **Guarda de rol:** al abrir el panel se verifica la sesión. Si no hay sesión `ADMIN`, se
  redirige a Login.
- **Cerrar sesión:** llama a `SessionManager.cerrarSesion()` (borra token y datos) y regresa
  a Inicio. No pide confirmación.
- **Volver a modo público:** regresa a Inicio **sin** cerrar la sesión.
- **Resumen:** mientras carga muestra "—". Si falla, muestra "No se pudo cargar el resumen"
  con botón **Reintentar**.
  - Totales, lugares, alertas y último video vienen del backend (`GET /admin/stats`).
  - Las **fotos pendientes** vienen de la **cola local de subida** (`data/local`), no del backend.
- Los números se formatean según el idioma del teléfono (puede verse "2.842" o "2,842").
- Cada tarjeta navega a su vista:

  | Tarjeta | Ruta | Vista |
  |---|---|---|
  | Recolector de imágenes | `admin/ubicacion-manual` | 7.3 |
  | Lugares | `admin/lugares` | 7.6 |
  | Mapa y alertas | `admin/mapa` | 7.8 |
  | Imágenes | `admin/imagenes` | 7.11 |
  | Videos | `admin/videos` | 7.13 |
  | Estadísticas | `admin/estadisticas` | 7.15 |
  | Ajustes (ícono) | `ajustes` | 6.7 |

**Accesibilidad:** cada tarjeta es un solo elemento para TalkBack (título + descripción); cada
dato del resumen se lee completo ("2.842 fotos en el dataset"); botones de 64 dp o más.
Los tamaños de texto están pensados para pantallas de ~400 dp de ancho y respetan la escala
de fuente del sistema; las tarjetas crecen en alto si el texto se agranda.

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/admin/panel/PanelAdminScreen.kt` | Pantalla (`PanelAdminScreen`), contenido sin estado (`PanelAdminContent`), `PanelAcciones` y previews |
| `ui/admin/panel/PanelAdminViewModel.kt` | Estado (`PanelUiState`), eventos (`SesionCerrada`, `SinSesion`), carga del resumen y cierre de sesión |
| `data/repository/AdminRepository.kt` | Contrato del resumen (`AdminRepository`) y stub temporal (**TODO:** reemplazar por la implementación real) |
| `domain/model/ResumenAdmin.kt` | Modelo del resumen: 6 campos que dan los 5 datos del panel (el último video usa número y fecha) |
| `ui/theme/CampusColors.kt` | Colores compartidos de las vistas admin |
| `session/SessionManager.kt` | Lectura de la sesión (nombre, rol) y `cerrarSesion()` |

**Navegación (`AppNav` en `MainActivity.kt`):**
```kotlin
composable("admin/panel") {
    PanelAdminScreen(
        onRecolector = { nav.navigate("admin/ubicacion-manual") },
        onLugares = { nav.navigate("admin/lugares") },
        onMapaAlertas = { nav.navigate("admin/mapa") },
        onImagenes = { nav.navigate("admin/imagenes") },
        onVideos = { nav.navigate("admin/videos") },
        onEstadisticas = { nav.navigate("admin/estadisticas") },
        onAjustes = { nav.navigate("ajustes") },
        onVolverModoPublico = { nav.popBackStack("inicio", inclusive = false) },
        onSesionCerrada = { nav.popBackStack("inicio", inclusive = false) },
        onSinSesion = { nav.navigate("login") { popUpTo("admin/panel") { inclusive = true } } },
    )
}
```

---

### 7.3 Ubicación manual inicial — `ui/admin/recoleccion/UbicacionManualScreen.kt`

![alt text](<assets/ubicacion_manual_iniciada.png>)

**Propósito:** fijar la coordenada exacta de partida antes de recolectar.

**Elementos:**
- **Mapa del campus a pantalla casi completa**, con zoom y desplazamiento.
- **Marcador arrastrable** (o toque para colocarlo) que representa dónde está parado.
- **Selector de orientación**: flecha rotatoria o botón "Usar brújula del teléfono" para
  fijar hacia dónde mira.
- Campos de **coordenadas** (x, y / lat, lon) mostrados y editables.
- Botón **"Usar mi última posición"** (para continuar desde el final del video anterior; crea un video nuevo).
- Fila **"Calibrar mi paso"** (vista 7.3b): muestra la longitud de paso en uso (calibrada o genérica de 0,72 m) y abre la calibración.
- Botón **"Confirmar y comenzar"**: crea el nuevo video (ej. `video3`) y empieza la recolección.
- Campo opcional **nombre del video** (por defecto autonumerado).
- Botón **Cancelar**.
- Mensaje de ayuda: "Colócate en un punto reconocible y marca tu posición exacta".

**Estado de implementación (2026-10-11):** **implementada** en `ui/admin/recoleccion/UbicacionManualScreen.kt`
(con `UbicacionManualViewModel.kt` y `UbicacionManualState.kt`) y su mapa `assets/ubicacion_manual.html` +
`ubicacion_manual.js` (compila y se ha abierto en dispositivo, 2026-10-12; el JS pasó `node --check`; ⚠ sin prueba funcional completa).
Detalle de piezas y cuidados en 11.5 («UbicacionManual»).

- **Mapa** Leaflet/OSM con **marcador arrastrable** (o toque para colocarlo), flecha de rumbo y etiquetas de
  los lugares conocidos (`LugaresRepository`). «Centrar» y +/− los dibuja Compose encima del `WebView`.
- **Orientación:** dial que se gira con el dedo (con acciones de TalkBack de ±15° y «Apuntar al norte») y botón
  «Usar brújula del teléfono» (`EscucharOrientacion`; norte **magnético**). Sin sensor de rotación el botón
  queda deshabilitado y queda el dial.
- **Coordenadas** (lat/lng, 6 decimales) **editables** en un diálogo; acepta coma o punto y valida ±90 / ±180.
- **«Usar mi última posición»:** copia punto y rumbo de la última foto del video más reciente; **no** confirma sola.
  Deshabilitado si no hay videos anteriores.
- **«Calibrar mi paso»** (2026-10-12): fila bajo «Usar mi última posición» que muestra la longitud en uso («0,72 m (valor genérico)» o «… (calibrada)»)
  y navega a `admin/calibracion` (7.3b). La longitud se lee al abrir la pantalla; al volver de la calibración se relee.
- **Nombre del video** autonumerado (`video_N`, constante `PREFIJO_VIDEO`; máx. 40 caracteres); vacío = el sugerido.
- **«Confirmar y comenzar»** deshabilitado hasta que haya punto. **No crea el video:** emite
  `UbicacionManualEvento.Confirmado(InicioRecoleccion)` (`domain/model/InicioRecoleccion.kt`).
- **Se quitó el botón GPS** de esta vista: ya no aplica aquí (decisión abierta 14 sigue abierta para `MapaPublicoScreen`).

Falta: la **foto de referencia** y el **badge de brújula «N»** del diseño no se hicieron (no hay especificación de la
foto; Leaflet no rota el mapa). «Confirmar y comenzar» **ya entrega** `InicioRecoleccion` a la vista 7.4 por
`SesionDeRecoleccion` (11.6, decisión abierta 15) y `AppNav` navega a `admin/recoleccion` (11.8).

---

### 7.3b Calibración de la longitud de paso — `ui/admin/calibracion/CalibracionScreen.kt`

*(Vista nueva sin diseño de referencia: no hay imagen en `assets/`. Se llega desde la fila «Calibrar mi paso» de 7.3.)*

**Propósito:** medir la longitud de paso **real del admin** con **una sola pasada** sobre un tramo de distancia conocida, para que el PDR
convierta pasos en metros con su paso y no con el valor genérico (0,72 m). Es la respuesta a la decisión abierta 16.

**Flujo (fases `PUNTOS → LISTO → CAMINANDO → RESULTADO → GUARDADA`):**
1. **Marcar el tramo:** el admin toca el mapa para fijar **A** (inicio) y **B** (fin); ambos se pueden arrastrar. La distancia A→B sale de la
   fórmula de haversine. «Limpiar puntos» los borra. Recomendado un tramo de **30 m o más** (mínimo 10 m).
2. **Inicio:** fija la posición del PDR en A, arranca el contador de pasos y anota los pasos de partida.
3. **Caminar** de A a B **como lo hará al recolectar** (mismo ritmo y forma de llevar el teléfono). Se muestran tramo, pasos y tiempo.
4. **Fin:** pasos = (`PdrEstado.pasos` al final) − (al inicio); `longitud = distancia / pasos`.
5. **Resultado:** si es válido muestra la longitud (y, solo como información, cadencia y velocidad); el admin puede **Guardar**, **Repetir** o
   cancelar. **Restablecer** vuelve al valor genérico de 0,72 m.

**Validación** (orden: tramo → pasos → rango): tramo ≥ 10 m, ≥ 15 pasos y longitud entre 0,40 y 1,20 m. Los umbrales de 10 m y 15 pasos son
**elección propia** (constantes de `CalibracionPaso`); el rango viene del encargo. Un valor guardado fuera de rango se ignora.

**Qué hace con el resultado:** se guarda en el dispositivo (`SharedPreferences` `campus_calibracion`) y **reemplaza** el valor genérico: al
crear un `PdrTracker`, la longitud se lee una sola vez, y de ahí en adelante `distanciaMetros = pasos × longitud calibrada` en la
recolección (7.4: contadores, disparador por distancia, deriva y trayectoria), sin más cambios (11.2).

**Estado de implementación (2026-10-12):** implementada en cinco baches (C1–C4 entregados; C5, integración, hecha salvo lo indicado abajo).

| Módulo | Archivos | Detalle |
|---|---|---|
| Dominio | `domain/usecase/CalibracionPaso.kt` (`CalibracionPaso`, `ResultadoCalibracion`, `MotivoInvalido`) | Lógica pura; 11.7 |
| Almacenamiento | `data/repository/CalibracionPasoRepository.kt` | `SharedPreferences`; 11.6 |
| PDR | parches a `sensors/PdrEngine.kt` y `sensors/PdrTracker.kt` | `LONGITUD_PASO_DEFECTO_M` y parámetro `longitudPasoM`; 11.2 |
| Estado y lógica | `ui/admin/calibracion/CalibracionState.kt`, `CalibracionViewModel.kt` | Su propio `PdrTracker`; 11.5 |
| Mapa A→B | `assets/calibracion_mapa.html`, `assets/calibracion_mapa.js`, `ui/admin/calibracion/componentes/MapaCalibracion.kt` | Puente `CalibracionBridge` (11.5 y 11.9) |
| Pantalla | `ui/admin/calibracion/CalibracionScreen.kt` | Sin scroll: el mapa ocupa el espacio sobrante (mín. 180 dp) |
| Pruebas | `test/.../domain/usecase/CalibracionPasoTest.kt` | JUnit4, **no ejecutado en Gradle** |
| Navegación | `MainActivity.kt` (`Permisos.ACTIVIDAD`, ruta `admin/calibracion`), punto de entrada en `UbicacionManualScreen.kt` | 11.3 y 11.8 |

**Verificado:** `CalibracionPaso.kt` y `PdrEngine.kt` compilan con kotlinc 2.0.21 y pasan 13 comprobaciones (haversine ≈ 33,4 m para
0,0003° de latitud; `longitud = distancia/pasos`; los cuatro motivos de rechazo; límites 0,40 y 1,20 m válidos; `duracionS = 0` sin
romper; sin posición no cuenta pasos; `distancia = pasos × longitud inyectada`; valor por defecto 0,72). El proyecto compila con todas las
piezas y la pantalla se abre en dispositivo desde 7.3. **Error corregido en dispositivo:** el mapa salía en negro porque
`calibracion_mapa.js` llamaba a `base.crearMapa(...)` (no existe) en vez de `MapaBase.crearMapa(...)` (11.9).
⚠ **Falta la prueba funcional completa:** calibrar en un tramo de ≥ 30 m, guardar, iniciar una recolección y comprobar que
`distanciaMetros ≈ pasos × longitud guardada` y que el disparador de 5 m dispara cada ≈ `5 / longitud` pasos.

**Decisiones tomadas:**
- **Calibración por dispositivo con una sola pasada A→B**, no por cadencia ni por altura: resuelve la decisión abierta 16 (longitud de paso).
- La longitud se **inyecta en `PdrTracker`** (parámetro del constructor) y se lee **una sola vez, al crearlo**: recalibrar no cambia un tracker ya creado.
- La calibración usa **su propio `PdrTracker`** y mide por **resta** de `PdrEstado.pasos` (Fin − Inicio), porque `PdrEngine.onPaso` no cuenta pasos sin posición inicial.
- Valor genérico por defecto **0,72 m** (`PdrEngine.LONGITUD_PASO_DEFECTO_M`). El encargo decía 0,70 m: **sin confirmar**; basta cambiar la constante.
- Almacén `SharedPreferences` sin cifrar (`campus_calibracion`): `longitud_paso_m`, `pasos`, `distancia_m`, `fecha_ms`. No es un dato sensible y no hay un almacén genérico de preferencias.
- Pantalla **sin scroll**: un `WebView` dentro de un scroll vertical se pelea con el arrastre del mapa.

**Pendiente / fuera de alcance:**
- **Probar la pasada completa en dispositivo** (ver arriba) y **ejecutar `CalibracionPasoTest`** en Gradle.
- **Promediar varias pasadas** (hoy una sola medición, sin historial).
- ⚠ **Recalibrar tras el cambio de detector (2026-10-12):** una longitud guardada con el sensor de hardware ya no sirve; el detector por acelerómetro cuenta distinto. Hasta recalibrar, `distanciaMetros` puede salir sesgada. Como ya hay una sola fuente de pasos, desaparece el riesgo de calibrar con una y recolectar con otra (antes pendiente: guardar la `FuentePasos`).
- Relación con la unidad «metros / pasos» de Ajustes (6.7).
- La precisión depende de **marcar bien A y B**: con ~2 m de error total, un tramo de 10 m da hasta ~20 % de error y uno de 30 m, ~7 %.
- **Sin internet el mapa no carga** y no se pueden marcar A y B: la calibración es inutilizable sin mapa (decisión 13).
- **No corrige la deriva de la brújula** ni hace fusión (`domain/fusion/`).

---

### 7.4 Recolección en curso — `ui/admin/recoleccion/RecoleccionScreen.kt`

![alt text](<assets/recoleccion_en_curso.png>)

**Propósito:** recolectar fotos con coordenadas mientras el admin camina.

**Elementos:**
- **Mapa en vivo** con la trayectoria recorrida, la posición actual y la orientación, y
  los puntos donde ya se tomaron fotos (marcadores/heatmap de cobertura).
- **Vista previa de cámara** (pequeña, esquina).
- **Contadores**: fotos tomadas, distancia recorrida, pasos, duración del video.
- **Indicador de calidad del seguimiento** (precisión estimada / deriva acumulada).
- **Indicador de captura automática** (parpadeo al tomar cada foto).
- Botón **"Pausar / Reanudar"**.
- Botón **"Reubicarme manualmente"** (re-anclar en el mapa para corregir el error
  acumulado).
- Botón **"Marcar punto de interés"** (asocia la coordenada actual a un lugar existente
  o nuevo).
- Botón **"Agregar alerta aquí"**: abre el formulario de alerta (vista 16) con la coordenada
  actual ya cargada; el admin escribe o dicta el mensaje y guarda sin interrumpir la
  recolección.
- Las **alertas ya existentes** se muestran en el mapa en vivo.
- Botón **"Finalizar video"** (con confirmación).
- **Nombre del video actual** visible en la parte superior (ej. "video3").
- Ajustes rápidos: intervalo de captura automática (por tiempo/distancia).
- Alertas: foto borrosa, poca luz, batería baja, almacenamiento bajo.

**Comportamiento:** actualiza la coordenada con PDR y toma fotos automáticamente
guardándolas con coordenada y orientación; guarda localmente de forma continua para no
perder datos si la app se cierra; mantiene la pantalla activa y funciona en primer plano.

**Estado de implementación (2026-10-11):** implementada en cinco baches. Compila y funciona según quien la escribió
(sin pruebas automáticas). Diseño: `assets/recoleccion_en_curso.png`.

| Módulo | Archivos | Detalle |
|---|---|---|
| Dominio | `domain/model/FotoRecolectada.kt` (`FotoRecolectada`, `DatosFoto`, `ResumenRecoleccion`), `domain/model/SesionRecoleccion.kt` (`SesionDeRecoleccion`), `domain/usecase/DisparadorCaptura.kt` (`DisparadorCaptura`, `ModoCaptura`, `Deriva`) | 11.6 y 11.7 |
| Almacenamiento | `data/repository/RecoleccionRepository.kt` (`RecoleccionRepositoryLocal`) | `files/recoleccion/<rec_NNNN>/` (11.6) |
| Estado y lógica | `ui/admin/recoleccion/RecoleccionState.kt`, `RecoleccionViewModel.kt` | Dueño del PDR (11.2, «Flujo de captura de la recolección») |
| Mapa en vivo | `assets/recoleccion_mapa.html`, `assets/recoleccion_mapa.js`, `ui/admin/recoleccion/componentes/MapaRecoleccion.kt` | Puente `RecoleccionBridge` (11.5 y 11.9) |
| Pantalla | `ui/admin/recoleccion/RecoleccionScreen.kt`, `componentes/PanelesRecoleccion.kt` | Dueña de CameraX (11.5) |
| Navegación | `MainActivity.kt` (`AppNav`) | Rutas `admin/recoleccion` y `admin/recoleccion/resumen` (11.8) |

**Qué quedó hecho de los elementos de arriba:** mapa en vivo (posición con rumbo, trayectoria, fotos tomadas y alertas), vista previa
de cámara, los cuatro contadores (fotos de 200, distancia, pasos, duración), calidad del seguimiento (precisión y deriva),
indicador de captura (destello y «Foto tomada»), Pausar / Reanudar, **Reubicarme manualmente** (alfiler arrastrable en el mapa),
**Agregar alerta aquí** (con `AlertaFormSheet`), **Finalizar video** (con confirmación), nombre del video, intervalo de captura
(cada 3, 5 o 10 m, o cada 3 o 5 s; por defecto 5 m) y avisos de batería baja y almacenamiento bajo. Se guarda en disco **de forma
continua** (`manifest.json` actualizado en cada foto) y la pantalla se mantiene encendida; en segundo plano (`ON_STOP`) la grabación se pausa sola.

**Decisiones tomadas:**
- **Datos entre vistas con un holder en memoria** (`SesionDeRecoleccion`), no argumentos de ruta: resuelve la decisión abierta 15 para este flujo (7.3 → 7.4 → 7.5).
- **Almacenamiento propio** (`RecoleccionRepository`), separado de `VideoRepository`: éste es la fuente de verdad (futuro `RemoteVideoRepository`); no se amplió como pedía 11.6. Ver «Pendiente» más abajo.
- Fotos y manifest en `files/recoleccion/<rec_NNNN>/photos/NNNN.jpg` y `manifest.json` (misma forma que `assets/videos/`); prefijo `rec_` para no chocar con los datos de prueba (`vid_`); fechas en ISO-8601 (`yyyy-MM-dd'T'HH:mm:ssXXX`).
- Deriva estimada = 4 % de la distancia desde el último ancla (heurística provisional; decisión abierta 16).
- **Distancia = pasos × longitud de paso calibrada** (7.3b; 0,72 m si no hay calibración): el `PdrTracker` de 7.4 la lee una vez al crearse, así que calibrar **antes** de entrar a 7.4.

**Pendiente / fuera de alcance:**
- **«Marcar punto de interés»:** el botón se dibuja **deshabilitado** («Próximamente»); depende de 7.6 y 7.7.
- **Foto borrosa y poca luz:** los avisos existen pero **nunca se activan** (el control de calidad `camera/CalidadImagen.kt` sigue sin uso).
- **Alertas:** las existentes **no se cargan** en el mapa en vivo y las creadas durante la grabación **se pierden al salir** (no hay `AlertasRepository`; guardar en backend es de 7.8).
- **Vista 7.5:** «Finalizar» lleva a un placeholder en blanco (`admin/recoleccion/resumen`).
- **Subida al backend** y **retomar** una grabación tras matar el proceso (`buscarEnCurso()` existe, pero no se usa: se muestra el error `SIN_INICIO`).
- **Ver lo recolectado en Galería, Lista y Detalle de video:** `AssetsVideoRepository` solo lee `assets/`. Hace falta un `VideoRepository` compuesto (assets + `files/recoleccion/`) y un parser de manifest compartido.
- **Diseño:** sin brújula «N», el mapa no rota y usa teselas de OSM (no satélite).

---

### 7.5 Resumen de video — `ui/admin/recoleccion/ResumenVideoScreen.kt`

![alt text](<assets/resumen_de_video.png>)

**Elementos:**
- Nombre del video (editable) y estadísticas: duración, distancia, nº de fotos.
- **Mapa con la trayectoria final** y cobertura.
- **Revisión rápida de fotos** (carrusel) con opción de descartar.
- Botón **"Subir y procesar"** (con barra de progreso y estado por foto: pendiente /
  subida / embedding generado / error).
- Botón **"Guardar y subir después"**.
- Botón **"Descartar video"** (con confirmación; borra el video y todas sus fotos locales).
- Opción de **corregir la trayectoria** (re-anclar puntos) antes de subir.

---

### 7.6 Lista de lugares — `ui/admin/lugares/LugaresScreen.kt`

![alt text](<assets/lista_de_lugares.png>)

**Elementos:**
- Barra de búsqueda y filtro por categoría.
- **Lista de lugares**: nombre, categoría, nº de fotos asociadas, coordenada.
- Botón flotante **"Nuevo lugar"**.
- Toque en un lugar → editar. Opciones: editar, eliminar (con confirmación), ver fotos.
- Alternar entre **vista de lista** y **vista de mapa**.

### 7.7 Formulario de lugar — `ui/admin/lugares/LugarFormScreen.kt`

![alt text](<assets/formulario_de_lugar.png>)

**Elementos:**
- Campos: **nombre**, **sinónimos/alias** (para el reconocimiento de voz), **descripción**
  (texto que se lee al usuario), **categoría**.
- **Selector de coordenada en mapa** (punto de llegada/entrada del lugar).
- **Referencias cercanas** (texto para describir alrededores).
- Fotos asociadas (lista, solo lectura o con enlace a galería).
- Botones **Guardar** / **Cancelar** / **Eliminar**.
- Validaciones (nombre único, coordenada obligatoria).

---

### 7.8 Editor de mapa y alertas — `ui/admin/mapa/EditorMapaScreen.kt`

![alt text](<assets/editor_de_mapa_y_alertas.png>)

**Propósito:** permitir al admin modificar el mapa agregando, moviendo, editando y eliminando
alertas de obstáculo (y visualizando lugares). El mapa es **OpenStreetMap en línea con Leaflet**,
dentro de un `WebView` (ver 2.6); el formulario de alerta (7.9) es nativo.

**Elementos:**
- **Cabecera**: botón Atrás, título y chip de estado: **"Cambios pendientes (n)"** (ámbar) o
  **"Todo sincronizado"** (verde).
- **Marcadores de alertas** con ícono según tipo y color del borde según prioridad (rojo = Alta,
  ámbar = Normal); las inactivas se ven atenuadas. Al tocar un marcador se abre una **tarjeta**
  con tipo, prioridad, mensaje, posición, radio de activación y los botones Mover / Editar /
  Eliminar.
- **Círculo del radio de activación** de la alerta seleccionada. El radio se cambia desde el
  formulario (7.9) y el círculo se redibuja en vivo.
- Botón flotante **"Nueva alerta"** → modo colocar: se toca el mapa para fijar el punto y se
  abre el formulario de alerta.
- **Mover** una alerta desde su tarjeta: el marcador se vuelve arrastrable (ver detalle abajo).
- **Selector de capas** (alertas, lugares, cobertura de fotos, rutas). *Cobertura y rutas ya
  tienen su interruptor, pero todavía no se cargan datos.*
- **Filtros** desplegables: tipo, prioridad y estado.
- Botón **"Mi posición"** (centra el mapa en la posición actual del admin).
- Botón **"Ver lista"** (arriba a la derecha y abajo) → Lista de alertas (7.10).
- Botón **Guardar / Sincronizar** con un punto indicador (ámbar con pendientes, verde sin ellos).
- **Atribución "© OSM"** visible en el mapa (obligatoria por la licencia de OpenStreetMap).

**Comportamiento:** guardar, mover o eliminar se aplica al instante en el mapa y queda como
cambio pendiente; **"Guardar / Sincronizar"** los envía al backend, y desde ahí se propagan a
los dispositivos de los usuarios en su siguiente sincronización.

**Detalle de la implementación:**
- **Local primero:** guardar, mover o eliminar una alerta se aplica de inmediato en el repositorio
  local y su `id` se agrega al conjunto de **pendientes** (el número del chip son alertas con
  cambios, no operaciones). "Guardar / Sincronizar" los envía; si falla, siguen pendientes. Si no
  hay pendientes, avisa "No hay cambios pendientes".
- **Colocar:** "Nueva alerta" activa el modo colocar (el botón pasa a "Cancelar"); el siguiente
  toque en el mapa fija el punto y abre el formulario de alerta (7.9).
- **Mover:** el botón "Mover" de la tarjeta vuelve arrastrable **solo ese marcador**; un aviso
  inferior ofrece "Listo" y "Cancelar" (cancelar restituye la posición original). La tarjeta se
  oculta mientras se mueve.
- **Borrador en vivo:** mientras el formulario está abierto, la alerta en edición se dibuja en el
  mapa con sus cambios (radio, prioridad, tipo) antes de guardarse. El ViewModel lo envía al mapa
  como `borradorJson`.
- Tocar el mapa vacío deselecciona. Eliminar pide confirmación (en la tarjeta y en el formulario).
- **Botón Atrás** (del sistema o de la cabecera): sale primero de los modos temporales, en este
  orden: mover → colocar → formulario abierto → alerta seleccionada. Si no queda ninguno y hay
  cambios sin sincronizar, pide confirmar antes de salir.
- Los filtros nunca ocultan la alerta seleccionada ni el borrador.
- Reglas: radio por defecto **15 m** (slider de 5 a 100 m, de 5 en 5); mensaje obligatorio,
  máximo **200 caracteres**.

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/admin/mapa/EditorMapaScreen.kt` | `EditorMapaScreen` (la que usa el NavHost: conecta ViewModel, formulario y navegación), `EditorMapaContent` (solo dibuja el mapa con `MapaWebView`), interfaz `EditorMapaEventos` y el puente `EditorPuente` |
| `ui/admin/mapa/EditorMapaViewModel.kt` | Estado (`EditorMapaUi`), formulario en edición, validación, pendientes y sincronización (**hoy simulada**) |
| `ui/admin/mapa/AlertaFormSheet.kt` | Formulario de alerta (vista 7.9), hoja inferior de Material 3 |
| `domain/model/Alerta.kt` | Modelos `Alerta` y `Lugar` |
| `app/src/main/assets/editor_mapa.html` | Interfaz del editor (estilos y estructura) |
| `app/src/main/assets/editor_mapa.js` | Capas, filtros, modos (colocar / mover) y borrador; usa `mapa_base.js` para el puente, `toast`, `confirmar`, medidas y mapa (11.9) |
| `app/src/main/assets/mapa_base.js` | Base común de las páginas de mapa: puente, `toast`, `dialogo`, medidas, `setInsets`, `onAtras` por defecto y mapa Leaflet (11.9) |
| `map/MapaWebView.kt` | `MapaWebView`, `MapaWeb` y `PuenteWeb`: la fábrica común del `WebView` de todos los mapas (11.9) |

**Puente WebView ↔ Android (`EditorBridge`):** los datos viajan como JSON; la alerta tiene los
campos `id, lat, lng, mensaje, tipo, prioridad, radio, activa` (tipo: `agua`, `mobiliario`,
`escalones`, `obra`, `vehiculos`, `otro`; prioridad: `normal` o `alta`).

| Dirección | Función | Descripción |
|---|---|---|
| Web → Kotlin | `listo()` | La página cargó; Kotlin responde enviando alertas, lugares y pendientes |
| Web → Kotlin | `abrirFormulario({id, lat, lng})` | Abre el formulario (`id` nulo = alerta nueva) |
| Web → Kotlin | `cancelarFormulario()` | El usuario salió del formulario desde el mapa (botón Atrás) |
| Web → Kotlin | `moverAlerta(id, lat, lng)` | Nueva posición confirmada con "Listo" |
| Web → Kotlin | `eliminarAlerta(id)` | Eliminación confirmada |
| Web → Kotlin | `sincronizar()` / `verLista()` / `pedirMiPosicion()` / `salir()` | Acciones de los botones |
| Kotlin → Web | `cargarAlertas(json)` / `cargarLugares(json)` | Reemplazan los datos del mapa |
| Kotlin → Web | `setPendientes(n)` | Actualiza el chip y el punto del botón Guardar |
| Kotlin → Web | `setBorrador(json \| null)` | Dibuja (o quita) el borrador del formulario |
| Kotlin → Web | `setMiPosicion(lat, lng)` | Dibuja la posición del admin y centra el mapa |
| Kotlin → Web | `onAtras()` | Lo invoca el `BackHandler`; el JS decide qué cerrar y llama a `salir()` |

**Navegación (`AppNav` en `MainActivity.kt`):**
```kotlin
composable("admin/mapa") {
    EditorMapaScreen(
        onVolver = { nav.popBackStack() },
        onVerLista = { /* vista 7.10 aún no existe */ },
        posicionAdmin = { null },   // luego: la posición del PDR, como Pair(lat, lng)
    )
}
```

**Requisitos:** `editor_mapa.html` y `editor_mapa.js` en la raíz de `assets/`, permiso `INTERNET`,
y conexión a internet (Leaflet y las teselas se descargan en línea; ver decisión abierta 13). Si
la página no carga, `EditorMapa` en Logcat muestra los errores del `WebView`.

**Pendiente:** conectar el repositorio local (Room) y la API real (`/admin/alerts`), cargar las
capas de cobertura y rutas, pasar la posición real del admin en `posicionAdmin`, y completar el
formulario (dictado por voz, "Escuchar cómo sonará", vigencia y "Ajustar en el mapa").


### 7.9 Formulario de alerta — `ui/admin/mapa/AlertaFormSheet.kt`

![alt text](<assets/formulario_de_alerta.png>)

Hoja inferior (bottom sheet) o diálogo reutilizable desde el editor de mapa y desde la
recolección.

**Estado:** implementada en `ui/admin/mapa/AlertaFormSheet.kt` (mensaje, tipo, prioridad, radio,
estado, validación y eliminar con confirmación). Faltan dictado por voz, "Escuchar cómo sonará",
vigencia y "Ajustar en el mapa".

**Elementos:**
- **Campo de mensaje** (texto libre, multilínea) con botón de **dictado por voz**. Texto de
  ayuda: "Escribe exactamente lo que se le dirá al usuario".
  Ej.: *"Ten cuidado, hay bancas cerca, no te vayas a estrellar"*.
- Botón **"Escuchar cómo sonará"** (previsualiza el mensaje con la voz de la app).
- **Tipo** (selector): agua, mobiliario, escalones, obra, vehículos, otro.
- **Prioridad** (Normal / Alta).
- **Radio de activación** (slider en metros, con vista previa del círculo en el mapa).
- **Coordenada** (mostrada, con botón "Ajustar en el mapa").
- **Estado** (switch Activa/Inactiva).
- **Vigencia** opcional (fecha inicio/fin).
- Botones **Guardar**, **Cancelar**, **Eliminar** (con confirmación, solo si ya existe).
- Validaciones: mensaje obligatorio y de longitud razonable (para que se lea en pocos
  segundos), coordenada obligatoria.

### 7.10 Lista de alertas — `ui/admin/mapa/AlertasScreen.kt`

![alt text](<assets/lista_de_alertas.png>)

**Elementos:**
- Buscador por texto del mensaje y filtros por tipo, prioridad y estado.
- **Lista**: ícono de tipo, mensaje (resumido), prioridad, radio, estado y fecha de
  modificación.
- Acciones por fila: **editar**, **activar/desactivar**, **ver en el mapa**, **eliminar**.
- Botón flotante **"Nueva alerta"**.
- Alternar a la **vista de mapa**.

### 7.11 Galería de imágenes — `ui/admin/imagenes/GaleriaScreen.kt`

![alt text](<assets/galeria_de_imagenes.png>)

**Estado:** implementada con datos locales (`assets/`). Pendientes: vista de mapa, filtro por fecha,
botón "Subir imágenes" y conexión con el backend (ver al final).

**Elementos:**
- **Encabezado**: contador de imágenes (según los filtros activos) y chip "Página x de y".
- **Búsqueda** por nombre de archivo, lugar o video, con botón para borrar el texto.
- **Filtros** (menús desplegables, opción "Todos/Todas" para quitarlos): **lugar**, **video**,
  **estado** (subida / procesada / error) y **calidad** (alta / normal / baja). Los filtros activos
  se resaltan. Cambiar un filtro vuelve a la página 1 y limpia la selección.
- **Cuadrícula** de 2 columnas. Cada tarjeta muestra la miniatura, el nombre del archivo, el lugar
  ("Sin lugar" si no tiene), el estado con punto de color (azul = subida, verde = procesada,
  rojo = error) y una estrella si es de alta calidad.
- **Selección múltiple**: pulsación larga sobre la tarjeta o toque en el círculo de la esquina.
  Con una selección activa, un toque alterna la foto en vez de abrirla, y el botón Atrás primero
  cancela la selección.
- **Barra de acciones en lote** (siempre visible, con el contador de seleccionadas): **Reasignar**
  (diálogo para escribir el lugar) y **Eliminar** (diálogo de confirmación). Se habilitan solo con
  al menos una foto seleccionada.
- **Paginación** de 24 fotos por página (`FOTOS_POR_PAGINA`), con paginador numérico (ej. `1 2 3 … 8`)
  visible solo si hay más de una página. No hay scroll infinito.
- **Alternar cuadrícula / mapa**. Hoy la opción Mapa muestra un mensaje provisional con el número de
  fotos filtradas.
- Toque en una foto (sin selección activa) → **Detalle de imagen** (vista 7.12).
- Estados vacíos: indicador de carga, mensaje de error con "Reintentar" y "No hay imágenes con estos
  filtros" con "Limpiar filtros".

**Accesibilidad:** botones y chips de 48 dp o más; cada tarjeta se lee como un solo elemento
(archivo, video, lugar, estado, calidad y si está seleccionada); la selección se hace con pulsación
larga, que TalkBack expone como acción ("Seleccionar"); el encabezado está marcado como título.

**Fuente de datos (provisional, local):** `AssetsVideoRepository` lee los videos empaquetados en
`app/src/main/assets/videos/<video_id>/`. Se usa la misma estructura que tendrá S3:

```
videos/
└── vid_0001/
    ├── manifest.json
    ├── photos/0001.png ...
    └── thumbs/0001.png ...      (si falta una miniatura se usa la foto original)
```

`manifest.json` (un solo archivo por video):

| Campo | Obligatorio | Descripción |
|---|---|---|
| `video_id`, `name`, `created_at` | `name` recomendado | Identificador inmutable del video y nombre visible (renombrable). ⚠ Hoy el código **no lee `video_id`**: usa el nombre de la carpeta como id (ver 11.6) |
| `photos[].id`, `file`, `lat`, `lng` | Sí | Id dentro del video, ruta relativa y coordenadas (WGS84) |
| `photos[].thumb` | No | Ruta relativa de la miniatura |
| `photos[].heading` | No | Rumbo en grados, 0 = norte, sentido horario |
| `photos[].captured_at` | No | Fecha/hora de captura |
| `photos[].lugar`, `estado`, `calidad` | No | Valores por defecto: sin lugar, `procesada`, `normal` |

> El `manifest.json` es solo la semilla local. Cuando exista el backend, la fuente de verdad serán
> su base de datos (metadatos) y S3 (archivos, bucket privado con URLs prefirmadas de vida corta).
> Cambiar `AssetsVideoRepository` por un `RemoteVideoRepository` no afecta a las pantallas: `Foto`
> ya recibe las URLs resueltas.

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/admin/imagenes/GaleriaScreen.kt` | Pantalla (`GaleriaScreen`), contenido sin estado (`GaleriaContent`), `GaleriaAcciones` y previews |
| `ui/admin/imagenes/GaleriaViewModel.kt` | Estado (`GaleriaUiState`, `GaleriaFiltros`, `ModoVista`), filtros, búsqueda, selección, paginación y acciones en lote |
| `data/repository/VideoRepository.kt` | Contrato (`VideoRepository`) e implementación local (`AssetsVideoRepository`) (**TODO:** `RemoteVideoRepository`) |
| `domain/model/Foto.kt` | `Foto`, `Video`, `EstadoFoto`, `CalidadFoto` |

**Dependencia:** Coil para cargar imágenes (`io.coil-kt:coil-compose:2.7.0`); entiende las URLs
`file:///android_asset/...` y, más adelante, las URLs prefirmadas de S3.

**Navegación (`AppNav` en `MainActivity.kt`):**
```kotlin
composable("admin/imagenes") {
    GaleriaScreen(
        onVolver = { nav.popBackStack() },
        onAbrirImagen = { _, _ -> }, // placeholder: aún no existe la vista 7.12
    )
}
```
> Cada ruta debe registrarse **una sola vez**: si se repite, la última registrada reemplaza a la
> anterior (un placeholder vacío puede tapar la pantalla real).

**Pendiente:**
- **Vista de mapa**: dibujar las fotos filtradas en el mapa Leaflet (se resuelve junto con 7.14);
  con un filtro de video activo debe mostrar solo las fotos de ese video.
- **Filtro por fecha**: requiere `captured_at` real en las fotos.
- **Eliminar y Reasignar** hoy solo modifican la memoria (los assets son de solo lectura) y se
  pierden al salir de la pantalla; conectar con el backend (`/admin/images`). Reasignar debe usar un
  selector de lugares reales (vista 7.6) en vez de texto libre.
- **Navegar al detalle** (7.12) con `videoId` y `fotoId`.
- Botón **"Subir imágenes"** (opcional).
- Mover la paleta (`GaleriaColores`) a `ui/theme/CampusColors.kt`.

### 7.12 Detalle de imagen — `ui/admin/imagenes/DetalleImagenScreen.kt`

![alt text](<assets/detalles_de_imagen.png>)

**Elementos:**
- Imagen grande con zoom.
- **Metadata**: coordenada, orientación, fecha/hora, **video al que pertenece** (enlace al detalle del video), dispositivo, estado de
  procesamiento/embedding.
- **Minimapa** con el punto donde se tomó.
- **Corregir coordenada** (arrastrar en el mapa).
- Campo de **notas**.
- Botones: **Eliminar**, **Reasignar a lugar**, **Reprocesar embedding**.

---

### 7.13 Lista de videos — `ui/admin/videos/VideosScreen.kt`

![alt text](<assets/lista_de_videos.png>)

**Propósito:** ver todos los recorridos de recolección ("videos") y elegir uno para
inspeccionarlo o eliminarlo.

**Elementos:**
- **Lista de videos**: nombre (ej. "video1"), fecha, duración, distancia, nº de fotos y
  estado (en curso / pendiente de subir / procesado / con errores).
- **Minimapa o miniatura de trayectoria** por video.
- Ordenar por fecha / nombre / nº de fotos; buscador por nombre.
- Toque en un video → **Detalle de video** (vista 21).
- Acciones por fila (menú): **renombrar**, **reintentar subida**, **reprocesar
  embeddings**, **eliminar** (con la confirmación descrita en 7.14).
- Selector de videos para **comparar** cobertura (opcional): mostrar varios a la vez con
  distinto color.
- Indicador de videos pendientes sin sincronizar.
- Botón **"Nuevo video"** (lleva a la ubicación manual inicial).

---

### 7.14 Detalle de video — `ui/admin/videos/VideoDetalleScreen.kt`

![alt text](<assets/detalle_de_video.png>)

**Estado:** implementada con datos locales (`assets/`). Pendientes: duración, confirmación con
pulsación larga, progreso y reintento del borrado, y conexión con el backend (ver al final).

**Propósito:** al seleccionar un video, ver en el mapa **SOLO las fotos de ese video** y
poder renombrarlo o eliminarlo por completo. Se llega desde la Lista de videos (7.13).

**Elementos:**
- **Mapa** (OpenStreetMap con Leaflet, dentro de un `WebView`, igual que 7.8) donde se dibujan
  **únicamente** las fotos del video: un **marcador numerado por foto** (1, 2, 3… en orden de
  captura) con una **flecha de orientación** (0° = norte, sentido horario; sin flecha si la
  foto no tiene rumbo) y la **trayectoria** que las une. Al abrir, el mapa se encuadra para
  mostrar todo el recorrido (solo la primera vez: editar no mueve el mapa).
- **Conmutador "Mostrar otros videos"** (apagado por defecto): dibuja las fotos de los demás
  videos como puntos grises tenues, solo como contexto. Con un único video no muestra nada.
- **Encabezado**: botón Atrás, nombre del video, fecha de creación, nº de fotos y distancia
  recorrida (suma de los tramos entre fotos consecutivas).
- Al tocar un marcador: **tarjeta de vista previa** con la miniatura, la coordenada (6
  decimales), la orientación (grados y punto cardinal, p. ej. "180° S") y los botones
  **"Ver detalle"** (→ Detalle de imagen, vista 7.12) y **"Eliminar foto"**.
- **Tira de miniaturas** del video, sincronizada con el mapa: al tocar una miniatura se
  selecciona y se centra el mapa en su marcador (en el área libre entre la cabecera y el panel
  inferior); al tocar un marcador, la tira se desplaza hasta su miniatura. Tocar el mapa vacío
  o la ✕ de la tarjeta deselecciona.
- Botón **"Renombrar"**: diálogo con el nombre actual; "Guardar" se habilita solo si el
  nombre no está vacío y cambió (máx. 40 caracteres).
- Botón **"Eliminar video"** (rojo, separado del resto para evitar toques accidentales).

**Flujo de eliminación del video:**
1. Diálogo que indica el alcance: *"Vas a eliminar «video1» y sus 6 fotos. Esto quitará esas
   fotos del sistema de ubicación y no se puede deshacer."*
2. Confirmación reforzada: hay que **escribir el nombre exacto del video**; el botón
   "Eliminar video" permanece deshabilitado hasta que coincida.
3. Aviso "Video eliminado" y regreso automático a la lista de videos.
4. *(Pendiente con backend)* progreso del borrado (imágenes, embeddings e índice) y, si falla
   parcialmente, informar y permitir reintentar sin dejar fotos "huérfanas". En local el
   borrado es instantáneo y no puede fallar.

**Eliminar una foto:** botón en la tarjeta de vista previa, con confirmación. Si el video
queda con 0 fotos, se ofrece eliminarlo.

**Botón Atrás** (del sistema o de la cabecera): cierra primero el diálogo abierto, luego
deselecciona la foto y, si no queda nada, sale a la lista.

**Reglas:**
- Eliminar un video elimina **todas** sus fotos (y, con backend, sus embeddings y entradas del
  índice).
- No elimina alertas de obstáculo ni lugares.
- Los cambios se aplican de inmediato en la pantalla; el ViewModel los guarda en el
  repositorio y la Lista de videos (7.13) se refresca sola.

**Fuente de datos (provisional, local):** `AssetsVideoRepository` (ver 7.11) lee
`assets/videos/<video_id>/manifest.json`. Como los assets son de solo lectura, renombrar y
eliminar se guardan **en memoria** (`EdicionesLocales`, un objeto único del proceso): se
pierden al cerrar la app. Al cambiar algo, el repositorio emite por `cambios()` y las
pantallas abiertas (7.13 y 7.14) vuelven a cargar.

> `VideoRepository` ganó `renombrarVideo`, `eliminarVideo`, `eliminarFoto` y `cambios()`.
> Con el backend, `RemoteVideoRepository` los implementa con llamadas a la API y `EdicionesLocales`
> desaparece; las pantallas no cambian.

**Módulos que lo implementan:**

| Archivo | Responsabilidad |
|---|---|
| `ui/admin/videos/VideoDetalleScreen.kt` | `VideoDetalleScreen` (la que usa el NavHost: conecta ViewModel y navegación), `VideoDetalleContent` (solo dibuja el `WebView`) e interfaz `VideoDetalleEventos` |
| `ui/admin/videos/VideoDetalleViewModel.kt` | Carga el video y los demás, los serializa a JSON para el mapa y delega renombrar / eliminar foto / eliminar video al repositorio |
| `app/src/main/assets/video_detalle.html` | Interfaz (estilos y estructura): cabecera, tarjeta, tira de miniaturas y barra inferior |
| `app/src/main/assets/video_detalle.js` | Leaflet + OSM, marcadores con rumbo, trayectoria, selección sincronizada y diálogos; usa `mapa_base.js` para el puente, `toast`, `dialogo`, medidas y mapa (11.9) |
| `data/repository/VideoRepository.kt` | Contrato e implementación local (ver arriba) |
| `domain/model/Foto.kt` | `Video.distanciaMetros` (fórmula de haversine) |

**Puente WebView ↔ Android (`VideoBridge`):**

| Dirección | Función | Descripción |
|---|---|---|
| Web → Kotlin | `listo()` | La página cargó; Kotlin responde con insets, otros videos y el video |
| Web → Kotlin | `abrirFoto(id)` | "Ver detalle" de la foto (→ vista 7.12) |
| Web → Kotlin | `renombrar(nombre)` | Nuevo nombre confirmado |
| Web → Kotlin | `eliminarFoto(id)` | Eliminación de una foto confirmada |
| Web → Kotlin | `eliminarVideo()` | Eliminación del video confirmada |
| Web → Kotlin | `salir()` | Volver a la lista |
| Kotlin → Web | `cargarVideo(json)` | Reemplaza el video mostrado |
| Kotlin → Web | `cargarOtros(json)` | Fotos de los demás videos (capa de contexto) |
| Kotlin → Web | `setInsets(top, bottom)` | Alto de las barras del sistema (en dp) |
| Kotlin → Web | `onAtras()` | Lo invoca el `BackHandler`; el JS decide qué cerrar |

Formato de los datos:
- Video: `{ id, nombre, fecha, fotos: [{ id, url, thumb, lat, lng, rumbo }] }` (`fecha` como
  `"2026-10-09"`; `rumbo` puede ser `null`).
- Otros videos: `[{ id, nombre, fotos: [{ lat, lng }] }]`.

**Navegación (`AppNav` en `MainActivity.kt`):**
```kotlin
composable("admin/videos/{videoId}") { entrada ->
    val videoId = entrada.arguments?.getString("videoId") ?: return@composable
    VideoDetalleScreen(
        videoId = videoId,
        onVolver = { nav.popBackStack() },
        onAbrirImagen = { _, _ -> }, // placeholder: aún no existe la vista 7.12
    )
}
```

**Requisitos:** `video_detalle.html` y `video_detalle.js` en la raíz de `assets/`, permiso
`INTERNET` y conexión a internet (Leaflet y las teselas se descargan en línea; ver decisión
abierta 13). Las fotos se cargan desde `file:///android_asset/...`. Si la página no carga,
`VideoDetalle` en Logcat muestra los errores del `WebView`.

**Accesibilidad:** botones de 48 dp o más (miniaturas de 64 dp); cada miniatura y marcador
lleva su número ("Foto 3 de 6"); los diálogos son `alertdialog` y el campo de texto recibe el
foco al abrir.

**Pendiente:**
- **Duración** del video en el encabezado: requiere `captured_at` real en las fotos.
- **Confirmación reforzada por pulsación larga** (alternativa a escribir el nombre).
- **Progreso y reintento del borrado**, y manejo de fallo parcial, cuando exista el backend
  (`DELETE /admin/videos/{id}`).
- **Persistir** renombrar y eliminar (hoy solo en memoria) y dejar de mantener `EdicionesLocales`.
- **Galería (7.11)**: refrescarse cuando se eliminan fotos desde aquí (hoy solo las ve al reabrirse).
- **Navegar al Detalle de imagen (7.12)** con `videoId` y `fotoId`.
- **Nombre editable directamente en el encabezado** (hoy se edita con el botón "Renombrar").
- **Reutilizar la base común** (`mapa_base.js` + `MapaWebView`, ya extraídas; ver 11.9) en el modo Mapa de la galería (7.11) y en el minimapa de 7.12.

---

### 7.15 Estadísticas — `ui/admin/estadisticas/EstadisticasScreen.kt`

![alt text](<assets/estadisticas.png>)

**Elementos:**
- Filtro de periodo (hoy / 7 días / 30 días / personalizado).
- **Tarjetas resumen**: ubicaciones realizadas, rutas iniciadas, rutas completadas, tasa
  de éxito, confianza media.
- **Gráfico de barras**: lugares más buscados como destino.
- **Gráfico de líneas**: uso por día / tendencia.
- **Gráfico circular**: distribución por categoría de lugares.
- **Mapa de calor**: zonas donde más se ubican los usuarios y zonas con baja confianza
  (indica dónde falta recolectar fotos).
- **Alertas más activadas** (cuáles se anuncian más) y zonas con muchas alertas.
- Lista de **zonas con baja cobertura** o errores frecuentes.

---

## 8. Decisiones abiertas (por definir)

1. **Proveedor y uso de teselas del mapa:** hoy se usa `tile.openstreetmap.org` directamente.
   El servidor público de OSM tiene una política de uso aceptable que **no está pensada para
   tráfico intensivo** de una app en producción. Antes de publicar, decidir si se mantiene, si
   se cambia a un proveedor de teselas con plan/clave propia o si se monta un servidor propio.
   Si el campus tiene interiores donde el mapa no llega, definir cómo se representan.
2. **Grafo de caminos:** para calcular rutas se necesita un grafo de zonas transitables.
   ¿Lo dibuja el admin en el editor de mapa (nueva herramienta), o se deriva de las
   trayectorias recolectadas?
3. **Alertas de obstáculo (ya definido):** son puntos manuales en el mapa con mensaje. Queda
   por decidir: radio por defecto, si se anuncian solo las alertas cercanas a la ruta o
   todas, y si se complementa a futuro con detección por cámara (fuera del alcance actual).
4. **Frecuencia de corrección visual** durante la navegación (tiempo / distancia /
   incertidumbre) y su impacto en datos móviles y batería.
5. **Algoritmo de fusión** PDR + visual: filtro de Kalman vs. filtro de partículas.
6. **Funcionamiento sin conexión:** ¿se permite navegar solo con PDR si se pierde la red?
   Recordar que el mapa base de OSM necesita internet (solo se ve lo que está en caché); la
   navegación por voz sí podría continuar sin teselas.
7. **Privacidad:** las fotos de usuarios públicos enviadas al backend: ¿se almacenan o se
   descartan tras la consulta? ¿se avisa al usuario?
8. **SDK mínimo/objetivo** y dispositivos soportados (sensores y cámara).
9. **Moderación de alertas:** ¿cualquier admin puede crear/editar alertas, o hay un rol
   revisor? ¿Se guarda historial de cambios?
10. **Eliminación de videos:** ¿borrado definitivo inmediato, o "papelera" con recuperación
    durante unos días? ¿Se guarda un registro (quién y cuándo eliminó)? ¿Se permite
    que cualquier admin elimine videos de otros?
11. **Autenticación:** proveedor y modelo de roles (¿solo `USER`/`ADMIN` o más?).
12. **Conservación de fotos de escaneo:** hoy `CONSERVAR_FOTOS = true` guarda hasta 20
    escaneos en el teléfono. Definir si en producción se borran siempre tras enviarlas al
    backend (relacionado con la decisión 7, privacidad).
13. **Dependencias externas del `WebView`:** `index.html` carga Leaflet desde `unpkg.com` y
    las fuentes desde Google Fonts. Si no hay red, la página del mapa ni siquiera carga.
    Decidir si se **empaquetan localmente** en `assets/` (recomendado: así solo las teselas
    dependen de internet).
14. **GPS en el mapa:** ¿se conserva el botón GPS (requiere `ACCESS_FINE_LOCATION` y atender la
    geolocalización del `WebView`) o la posición inicial se fija solo manualmente / por fotos? Hoy `MapaPublicoScreen` **no** atiende la
    geolocalización: el botón GPS muestra un error. La vista 7.3 (`UbicacionManualScreen`) **ya no tiene** botón GPS.
15. **Datos compartidos entre vistas:** **resuelta para el flujo de recolección** (7.3 → 7.4 → 7.5) con un holder
    en memoria, `SesionDeRecoleccion` (11.6): `AppNav` no pasa argumentos de ruta. **Sigue abierta para el flujo
    público** (el destino elegido, la posición estimada, si hay ubicación vigente): la opción natural es el mismo
    patrón (por ejemplo `SesionDeNavegacion`, único por proceso, con `StateFlow`). Hay que decidirlo antes de 6.3 y
    6.5; al hacerlo, actualizar 11.8.
16. **Longitud de paso del PDR:** **resuelta** con la calibración por dispositivo de 7.3b (una pasada A→B; se guarda y
    reemplaza el 0,72 m genérico, que queda solo como valor por defecto). **Sigue abierto:** la deriva de la brújula, la deriva
    estimada de 7.4 (heurística provisional del 4 %, que habrá que reemplazar cuando exista corrección visual) y si conviene
    promediar varias pasadas o guardar con qué fuente de pasos se calibró (ver 7.3b).

---

## 9. Notas para quien implemente

- La **calibración de la longitud de paso** ya existe (7.3b): pedirle al admin que calibre en un tramo de 30 m o más **antes de la
  primera recolección** y que **camine igual** que al calibrar. Falta la calibración de la **deriva de la brújula**.
- Las capturas deben tener **control de calidad** (blur, exposición) antes de enviarse.
- Las subidas deben tolerar **mala conexión** (cola local con reintentos).
- Mantener un **registro de pruebas reales en dispositivo físico**: el emulador no
  reproduce sensores ni cámara de forma útil.
- Pruebas reales hechas en un Xiaomi 23028RA60L (Android 14). El reconocimiento de voz registra
  `not connected to the recognition service`: revisar que el teléfono tenga un servicio de voz
  activo y proteger la creación del `SpeechRecognizer` con `isRecognitionAvailable`.
- Reactivar el control de calidad (`CalidadImagen.kt`) cuando el flujo de captura esté estable.
- Probar el mapa en un **dispositivo físico**: los sensores llegan por `AndroidBridge` y el
  emulador no los reproduce bien. Si el mapa sale en blanco, revisar conexión a internet y
  que el `WebView` tenga JavaScript activado.
- **PDR:** la posición acumula error (longitud de paso calibrada una sola vez, deriva de la brújula) y todavía no hay
  corrección visual. Probarlo caminando un recorrido conocido en un dispositivo físico antes de
  usarlo para etiquetar fotos (7.4).
- Los sensores del PDR solo se liberan al salir de la composición (`PdrTracker.liberar()`): no hay
  manejo de `ON_STOP`, así que siguen activos si la app pasa a segundo plano.
- Sacar de `java/com/example/myapplication/` los archivos `archivos_zip.py`, `crear_archivos.py` y
  `out.zip`: no son código de la app.
- Quitar de `README.md` y de cualquier script/documentación las referencias a
  `eafit.mbtiles` (ya no se usa).
- Cualquier cambio de arquitectura debe reflejarse en este archivo y en `README.md`.
- Al crear o cambiar una pieza que otra vista pueda reutilizar, actualizar su entrada en la
  sección 11 **en el mismo cambio** (las entradas con ⚠ no están verificadas contra el código).

---

## 10. Estado de implementación

> Resumen de lo que **ya existe en el código** (actualizado el 2026-10-12). Solo se listan vistas
> implementadas o parciales; las demás aparecen en las secciones 5 a 7 y siguen pendientes
> (6.3, 6.5 a 6.7, 7.5 a 7.7, 7.10, 7.12 y 7.15; la 7.3, la 7.3b y la 7.4 ya están implementadas). Cuando una vista avance, se actualiza esta tabla.
>
> **Estado:** *Implementada* = pantalla funcional (puede depender de un stub o de datos locales);
> *Parcial* = existe solo una parte de lo descrito en su sección.

### Vistas

| Sección | Vista | Estado | Datos | Pendiente / notas |
|---|---|---|---|---|
| 6.1 | Inicio — `ui/inicio/InicioScreen.kt` | Implementada | Local | Explicación hablada previa al diálogo de permisos |
| 6.2 | Ubicarse (escaneo 360°) — `ui/ubicacion/EscaneoScreen.kt` | Implementada | **Stub** (`EscaneoBackend`) | Control de calidad sin uso; `CONSERVAR_FOTOS = true` (debe ser `false` al publicar, decisión 12) |
| 6.4 | Selección de destino — `ui/destino/SeleccionDestinoScreen.kt` | Implementada | **Stub** (`LugaresRepository`) | Backend (`GET /places`) con distancias reales; fotos de lugares (hoy ícono si no hay `imagenUrl`); pasar el destino a 6.5 tras el escaneo; ordenar por popularidad |
| 7.1 | Login — `ui/auth/LoginScreen.kt` | Implementada | **Stub** (`AuthRepository`) | Reemplazar por Retrofit/Ktor con `ApiConfig.kt` |
| 7.2 | Panel admin — `ui/admin/panel/PanelAdminScreen.kt` | Implementada | **Stub** (`AdminRepository`) | Reemplazar por la implementación real |
| 7.3 | Ubicación manual inicial — `ui/admin/recoleccion/UbicacionManualScreen.kt` | Implementada (compila y se abre en dispositivo) | Local (`assets/`) | «Calibrar mi paso» abre 7.3b y muestra la longitud en uso; «Confirmar y comenzar» ya entrega `InicioRecoleccion` a 7.4 (`SesionDeRecoleccion`); foto de referencia y badge «N» del diseño sin hacer; el nombre `video_N` choca con los ejemplos `video3` del documento (decisión por tomar) |
| 7.3b | Calibración de la longitud de paso — `ui/admin/calibracion/CalibracionScreen.kt` | Implementada (compila y se abre en dispositivo; ⚠ pasada completa sin probar) | Local (`SharedPreferences`) | Probar A→B + guardado + recolección con la longitud calibrada; ejecutar `CalibracionPasoTest`; promediar pasadas; guardar la fuente de pasos |
| 7.4 | Recolección en curso — `ui/admin/recoleccion/RecoleccionScreen.kt` | Implementada | Local (`files/recoleccion/`) | «Marcar punto de interés» (depende de 7.6 y 7.7); foto borrosa y poca luz (control de calidad sin uso); alertas existentes y persistencia de las nuevas (sin `AlertasRepository`); retomar tras matar el proceso; subida al backend; vista 7.5; ver lo recolectado en Galería/Videos (repositorio compuesto); brújula «N» y satélite del diseño |
| 7.8 | Editor de mapa y alertas — `ui/admin/mapa/EditorMapaScreen.kt` | Implementada | Local; sincronización **simulada** | Capas de cobertura y rutas sin datos; repositorio local (Room) y API real (`/admin/alerts`); posición real del admin |
| 7.9 | Formulario de alerta — `ui/admin/mapa/AlertaFormSheet.kt` | Implementada | Local | Dictado por voz, "Escuchar cómo sonará", vigencia y "Ajustar en el mapa" |
| 7.11 | Galería de imágenes — `ui/admin/imagenes/GaleriaScreen.kt` | Implementada | Local (`assets/`) | Vista de mapa (solo mensaje provisional), filtro por fecha, "Subir imágenes"; Eliminar y Reasignar solo en memoria |
| 7.13 | Lista de videos — `ui/admin/videos/VideosScreen.kt` | Implementada (versión mínima) | Local (`assets/`) | Duración, minimapa, orden y búsqueda, acciones por fila, comparar cobertura, "Nuevo video" |
| 7.14 | Detalle de video — `ui/admin/videos/VideoDetalleScreen.kt` | Implementada | Local (`assets/`) | Duración, confirmación por pulsación larga, progreso y reintento del borrado; renombrar y eliminar solo en memoria |

### Componentes transversales

| Componente | Estado | Ubicación | Notas |
|---|---|---|---|
| Navegación (`AppNav`) | Implementada | `MainActivity.kt` | Hoy vive en `MainActivity`, no en `ui/navigation/AppNavHost.kt`. Rutas con placeholder vacío: `admin/recoleccion/resumen` (7.5), `admin/lugares`, `admin/estadisticas`, `ajustes`. Cada ruta se registra una sola vez |
| Permisos (`Permisos`, `PedirPermisos`) | Implementada | `MainActivity.kt` | Cámara, micrófono y actividad física en un solo diálogo |
| Sesión | Implementada | `session/SessionManager.kt` | Sesión cifrada con rol `USER` / `ADMIN` |
| Registro de eventos | Implementada | `MyApp.kt`, `logs/AppLog.kt` | Logcat y archivo; captura de crashes |
| Configuración del backend | Implementada | `ApiConfig.kt` | URL base |
| Sensores y cámara | Implementada | `sensors/OrientationProvider.kt`, `camera/CapturaFoto.kt` | `camera/CalidadImagen.kt` sin uso por ahora |
| Seguimiento de posición (PDR) | Implementada (⚠ sin probar en dispositivo) | `sensors/PdrEngine.kt`, `sensors/StepDetector.kt`, `sensors/PdrTracker.kt` | Pasos **siempre por acelerómetro** (2026-10-12; ⚠ recalibrar la longitud de paso); longitud de paso calibrable (7.3b; 0,72 m por defecto, se lee una vez al crear el tracker); sin corrección visual ni fusión (`domain/fusion/`); sin manejo de `ON_STOP` propio (la recolección lo pausa desde su ViewModel, ver 11.2) |
| Mapa Leaflet público | Implementada (⚠ sin probar en dispositivo) | `assets/index.html`, `assets/app.js`, `map/MapaPublicoScreen.kt`, `map/PuentePdr.kt` | Solo dibuja: la posición la calcula `PdrTracker`. Aloja la ruta `admin/ubicacion-manual`. Dependencias externas en línea (decisión 13); botón GPS sin geolocalización (decisión 14) |
| Mapa del editor de alertas | Implementada | `assets/editor_mapa.html`, `assets/editor_mapa.js`, `assets/mapa_base.js`, `map/MapaWebView.kt` | Puente `EditorBridge`. Usa la base común (11.9; ⚠ Kotlin sin compilar) |
| Mapa del detalle de video | Implementada | `assets/video_detalle.html`, `assets/video_detalle.js`, `assets/mapa_base.js`, `map/MapaWebView.kt` | Puente `VideoBridge`. Usa la base común (11.9; ⚠ Kotlin sin compilar) |
| Mapa de la ubicación manual | Implementada (⚠ Kotlin sin compilar) | `assets/ubicacion_manual.html`, `assets/ubicacion_manual.js`, `ui/admin/recoleccion/UbicacionManualScreen.kt` | Puente `UbicacionBridge` (11.5). Usa `MapaWebView` (11.9) con `pasarInsets = false` y `manejarAtras = false`; **no** usa `MapaBase.iniciar` (⚠ no se revisó `mapa_base.js`) |
| Mapa en vivo de la recolección | Implementada | `assets/recoleccion_mapa.html`, `assets/recoleccion_mapa.js`, `ui/admin/recoleccion/componentes/MapaRecoleccion.kt` | Puente `RecoleccionBridge` (11.5). Usa `MapaBase.iniciar`/`crearMapa` y `MapaWebView` con `pasarInsets = false` y `manejarAtras = false` (11.9); teselas de OSM en línea (decisión 13) |
| Captura automática y deriva | Implementada | `domain/usecase/DisparadorCaptura.kt` | Lógica pura (`DisparadorCaptura`, `ModoCaptura`, `Deriva`); testeable sin emulador, aún sin pruebas. Deriva provisional (decisión 16) |
| Calibración de la longitud de paso | Implementada (⚠ lógica verificada con kotlinc; resto sin probar a fondo) | `domain/usecase/CalibracionPaso.kt`, `data/repository/CalibracionPasoRepository.kt`, `ui/admin/calibracion/` | Ver 7.3b y 11.5 a 11.7. `sensors` ahora depende de `data.repository` |
| Mapa de la calibración | Implementada | `assets/calibracion_mapa.html`, `assets/calibracion_mapa.js`, `ui/admin/calibracion/componentes/MapaCalibracion.kt` | Puente `CalibracionBridge` (11.5). Usa `MapaBase.iniciar` y `MapaBase.crearMapa` (11.9) y `MapaWebView` con `pasarInsets = false` y `manejarAtras = false`; teselas de OSM en línea (decisión 13) |
| Almacenamiento de la recolección | Implementada | `data/repository/RecoleccionRepository.kt`, `domain/model/SesionRecoleccion.kt`, `domain/model/FotoRecolectada.kt` | `files/recoleccion/<rec_NNNN>/`; separado de `VideoRepository` (11.6): lo recolectado aún no se ve en Galería/Videos |
| Repositorios | Mixto | `data/repository/` | `AuthRepository`, `AdminRepository` y `LugaresRepository` son stubs; `VideoRepository` tiene implementación local (`AssetsVideoRepository`); `RecoleccionRepository` tiene `RecoleccionRepositoryLocal` (`files/recoleccion/`); `CalibracionPasoRepository` guarda la longitud de paso en `SharedPreferences` (`campus_calibracion`) |
| Modelos de dominio | Implementada | `domain/model/` | `Usuario`, `Rol`, `Sesion`, `ResumenAdmin`, `Alerta`, `Lugar`, `LugarDestino`, `CategoriaLugar`, `Foto`, `Video`, `EstadoFoto`, `CalidadFoto`, `InicioRecoleccion`, `FotoRecolectada`, `DatosFoto`, `ResumenRecoleccion`, `SesionDeRecoleccion` |
| Componentes y tema compartidos | Parcial | `ui/theme/CampusColors.kt`, `ui/components/BannerEstado.kt` | `GaleriaColores` (galería y lista de videos) debe moverse a `CampusColors.kt` |
| Carga de imágenes | Implementada | Coil (`io.coil-kt:coil-compose:2.7.0`) | Lee `file:///android_asset/...` y, más adelante, URLs prefirmadas de S3 |
| Datos de prueba de videos | Implementada | `assets/videos/vid_0001/` | 1 video, 6 fotos, `manifest.json` (ver 7.11) |

> **Datos provisionales:** mientras no exista el backend, los videos y fotos salen de `assets/`
> y las ediciones (renombrar, eliminar) viven en memoria (`EdicionesLocales`) y se pierden al
> cerrar la app. Al conectar el backend, `RemoteVideoRepository` reemplaza a
> `AssetsVideoRepository` y `EdicionesLocales` desaparece; las pantallas no cambian.

---

## 11. Catálogo de piezas reutilizables y contratos entre vistas

> **Para qué sirve:** que quien construya una vista nueva (persona o IA) pueda reutilizar lo ya
> hecho **sin leer los archivos de las otras vistas**. Cada entrada dice *qué hace* la pieza,
> *cómo se usa* y *con qué cuidado*.
>
> **Reglas de mantenimiento**
> 1. Antes de crear algo (botón, tarjeta, lógica de voz, repositorio…), buscar aquí si ya existe.
> 2. Al crear o cambiar una pieza que otra vista pueda usar, actualizar su entrada **en el mismo cambio**.
> 3. Lo marcado con ⚠ **no está verificado contra el código**: confirmar antes de depender de ello.
> 4. Lo que vive en `ui/<vista>/componentes/` pertenece a esa vista aunque sea `public`. Si otra vista
>    lo necesita, se mueve a `ui/components/` y se actualiza la tabla 11.5.

### 11.1 Patrón de vista (se repite en Login, Inicio, Escaneo, Panel admin y Destino)

| Pieza | Convención |
|---|---|
| `XScreen` | Conecta: permisos, ViewModel, ciclo de vida y navegación. No dibuja detalles. |
| `XContent` | Sin lógica: recibe el `UiState` y las acciones, y dibuja. Lleva `@Preview`. |
| `XUiState` | Un `data class` en un único `StateFlow`. La UI solo lo lee; el ViewModel es el único que lo escribe. |
| `XEvento` | `sealed interface` para cosas de una sola vez (navegar, tomar foto). Va por `SharedFlow(extraBufferCapacity = n)` (Inicio, Escaneo, Destino) o `Channel.receiveAsFlow()` (Login; Panel admin con `Channel.BUFFERED`). La pantalla lo recoge en `LaunchedEffect(Unit)`. |
| Navegación | La pantalla **no** conoce `NavController`: recibe lambdas (`onVolver`, `onX`) y `AppNav` las conecta. |
| ViewModel | `AndroidViewModel(app)` si necesita contexto (voz, sonido); `ViewModel` con `Factory` si recibe repositorios (Login, Panel admin, Galería, Lista y Detalle de video). |
| Acciones | Si son muchas, se agrupan en una clase con lambdas (`GaleriaAcciones`, `DestinoAcciones`). |
| Colores | `CampusColors` (11.4). |
| Accesibilidad | `contentDescription` en todo; áreas de 48 dp o más (56–64 dp en las vistas públicas); avisos como *live region*. |

**Variantes verificadas (vistas admin y públicas)** (no son errores, pero conviene unificarlas al tocar cada vista):
- Nombre del `StateFlow` de estado: `state` (Panel, Login), `uiState` (Galería, Lista de videos), `ui` (Editor de mapa, Detalle de video) y `estado` (Inicio, Destino).
- `Factory`: la de `PanelAdminViewModel` recibe un `Context` y lo convierte a `applicationContext` por sí sola; las de `GaleriaViewModel` (`appContext`) y `VideoDetalleViewModel` (`appContext`, `videoId`) **esperan que ya se les pase el de la aplicación**: con el de una `Activity` se filtraría. Las pantallas actuales ya pasan `LocalContext.current.applicationContext`. `VideosViewModel.Factory(appContext)` también **espera el de la aplicación**; `LoginViewModel.Factory(context)` lo convierte por sí sola (como la de Panel). Inicio y Destino son `AndroidViewModel` y no llevan `Factory`.
- El Editor de mapa y el Detalle de video no usan `XEvento`: los eventos llegan de JavaScript a través de una interfaz (`EditorMapaEventos`, `VideoDetalleEventos`; 11.5) y el estado del editor se llama `EditorMapaUi`. Galería, Lista y Detalle de video no tienen flujo de eventos en el ViewModel: salir y navegar lo resuelven las lambdas de la pantalla.
- `@Preview`: lo tienen `PanelAdminContent` (3), `GaleriaContent` (2), `SeleccionDestinoContent` (1) y `LoginContent` (4: vacío, cargando, credenciales inválidas y sin conexión; faltan sin permisos, desconocido y contraseña visible). **No** lo tienen `VideosContent`, `EditorMapaContent`, `VideoDetalleContent` ni `InicioContent` (un `WebView` no se previsualiza, pero `VideosContent` sí podría). `PanelAdminContent` y `LoginContent` son `internal`; los demás `XContent` son públicos.
- Recolección del estado: `collectAsStateWithLifecycle()` en Panel, Editor, Detalle de video, Login, Inicio y Destino; `collectAsState()` en Galería y Lista de videos (sigue recogiendo con la pantalla en segundo plano).
- Acciones agrupadas: `PanelAcciones` (10 lambdas) y `GaleriaAcciones` (14), ambas `data class` con valores `{}` por defecto para los previews. `DestinoAcciones` (12 lambdas) es una `class` simple **sin** valores por defecto: su preview pasa doce `{}` a mano.
- Eventos de una sola vez (verificado en los ViewModels): Inicio y Destino usan `MutableSharedFlow(extraBufferCapacity = 1)` con `tryEmit` y **sin `replay`**: si nadie está recogiendo en ese instante, el evento **se pierde**. Login usa `Channel(BUFFERED)`, que sí espera al colector (pero admite **un solo** colector).
- `InicioContent` recibe parámetros sueltos (`escuchando`, `backendEnLinea`, `permisosFaltantes`…) en vez de `InicioUiState`, y no tiene `modifier`.

### 11.2 Voz, sonido y registro

| Pieza | Ubicación | Cómo se usa | Cuidado |
|---|---|---|---|
| `VoiceController` | `ui/inicio/VoiceController.kt` (paquete `ui.inicio`, aunque lo usan 3 vistas) | `VoiceController(context)` · `speak(texto: String, alTerminar: () -> Unit = {})` · `listen(onResult: (String) -> Unit, onFail: () -> Unit)` · `stopListening()` · `stopAll()` · `release()` en `onCleared`. Envuelve `TextToSpeech` y `SpeechRecognizer` en español de Colombia (`es-CO`). **Solo desde el hilo principal.** Un controlador por ViewModel. | Verificado contra el código. Comportamiento exacto:<br>• `speak` usa `QUEUE_FLUSH`: **corta** lo que se esté diciendo y el `alTerminar` anterior **no** se llama. Solo el último `speak` tiene callback.<br>• `alTerminar` se llama al terminar **o si hay un error** de TTS (no se distinguen).<br>• `stopAll()` no dispara `alTerminar` (no se sobreescribe `onStop`), pero un `alTerminar` que ya estaba encolado en el hilo principal sí llega: por eso el token (abajo) sigue siendo necesario.<br>• Si el TTS aún no está listo, `speak` queda pendiente y **solo se guarda el último**. Si el TTS falla al iniciar, `speak` nunca habla ni llama a `alTerminar`: un flujo que encadena `speak → listen` se queda parado. Poner siempre una salida por toque.<br>• Tras `release()` `speak` no hace nada (tampoco llama a `alTerminar`).<br>• `listen` cancela el reconocimiento anterior, **no** detiene el TTS (escuchar mientras habla capta la propia voz: llamar a `listen` desde el `alTerminar`) y **no** comprueba `RECORD_AUDIO` (sin permiso responde `onFail`).<br>• `onResult` recibe hasta **3 hipótesis unidas por espacio** (`"sí no sí"`); esto importa para `InterpretarRespuesta` (11.7).<br>• `onFail` cubre: reconocimiento no disponible (se llama **de forma síncrona**, antes de que `listen` retorne), error, silencio y sin resultados.<br>Candidato a mover a `voice/`. |
| `Comando` / `ComandoParser` | **Dentro de `ui/inicio/VoiceController.kt`** (no existe `ComandoParser.kt` aparte) | `ComandoParser.parse(texto): Comando` → `UBICARME`, `IR_A_LUGAR` o `NINGUNO`. | Quita tildes y pasa a minúsculas. `UBICARME` si hay la palabra "uno"/"1" o el texto contiene "ubic", "donde estoy", "donde estamos". `IR_A_LUGAR` si hay "dos"/"2" o contiene "ir a", "llevar", "lugar", "destino", "llegar". Si coinciden **ambos** o **ninguno** → `NINGUNO`. Cuidado: "ir a", "ubic" y "lugar" se buscan como *fragmento* del texto, así que también aciona con "salir a", "venir a" o "ubicación". No quita signos de puntuación (`"uno,"` no cuenta como la palabra "uno"). Solo sirve para el menú de Inicio; para nombres de lugares y sí/no, ver 11.7. |
| `FeedbackCaptura` | `ui/ubicacion/FeedbackCaptura.kt` | `FeedbackCaptura(ctx)` · `confirmar()` (vibra 120 ms + pitido de 120 ms) · `liberar()` | Verificado. Es `internal` (visible en todo el módulo), así que otra vista puede usarla. Liberar en `onCleared`. El pitido sale por el canal de **notificaciones** (volumen 80): con el teléfono en silencio solo vibra. Si el sistema no puede crear el generador de tonos, simplemente no suena (no falla). `liberar()` solo libera el tono; no usarla después de liberar. Necesita `VIBRATE` en el Manifest (sección 4). |
| `AppLog` | `logs/AppLog.kt` (`object`) | `AppLog.d(TAG, msg)` · `AppLog.i(TAG, msg)` · `AppLog.w(TAG, msg, t = null)` · `AppLog.e(TAG, msg, t = null)` · `AppLog.nuevaSesion(prefijo): String` · `AppLog.sesion` (lectura/escritura) · `AppLog.init(context)` (solo `MyApp`) | Verificado. **`d` e `i` no reciben excepción**: para registrar una usar `w` o `e`. Cada línea va a Logcat (`[sesion] texto`) y a `files/logs/app.log` con hora, nivel, tag, hilo y sesión. Rota a ~1 MB (pasa a `app.log.1`, que pisa al anterior: historial máximo ≈ 2 MB). **Antes de `AppLog.init` solo escribe en Logcat.** La escritura al archivo es **síncrona en el hilo que llama**: no registrar en bucles calientes (el sensor de orientación llega a ~50 Hz). `nuevaSesion` genera `prefijo-NNNNN` con 5 dígitos del reloj: sirve para seguir una vuelta, **no garantiza unicidad**. Los errores de escritura se tragan en silencio. ⚠ El `SimpleDateFormat` interno es compartido y no es seguro entre hilos: con registros simultáneos desde varios hilos la hora de una línea puede salir corrupta. **No hay función de exportar**: el archivo se consulta como dice la sección 4. Tags en uso: `App`, `CRASH`, `EscaneoVM`, `Camara`, `DestinoVM`. Verificado: `InicioViewModel`, `LoginViewModel` y `VideosViewModel` **no registran nada**. No registrar tokens ni lecturas de sensores. Se inicia en `MyApp.onCreate` (`AppLog.init(this)`, que además registra fabricante, modelo y versión de Android con el tag `App`). Las excepciones no capturadas se registran con el tag `CRASH` y luego se pasan al manejador anterior del sistema (la app se cierra igual). |

**Patrón de flujo hablado con token** (implementado y verificado en `SeleccionDestinoViewModel`: `hablar`, `escuchar`, `detenerVoz`; detalle en 11.5):
hablar → al terminar, escuchar → interpretar → hablar… Cada interrupción de la persona (toca algo,
pausa, sale) hace `token++` y `voz.stopAll()`; los callbacks de voz que llegan con un token viejo se
ignoran, así el flujo hablado no continúa después de que la persona tomó el control. El token hace
falta aunque `stopAll()` no llame a `alTerminar`: un `alTerminar` ya encolado en el hilo principal
llega igual (ver `VoiceController` arriba). Copiarlo en cualquier vista con diálogo por voz. Inicio y Escaneo no lo usan (Escaneo comprueba su `fase`).

**Ciclo de vida:** en `ON_STOP` la pantalla llama al ViewModel (`alPausar()`), que hace `voz.stopAll()` y baja `escuchando` (Inicio y Destino, verificado). Destino además sube el `token`; Inicio **no tiene token**, así que un `alTerminar` ya encolado todavía puede llamar a `escuchar()` justo después de pausar (⚠ deducido del comportamiento de `VoiceController`, no reproducido).

#### Seguimiento de posición (PDR) (`sensors/PdrEngine.kt`, `sensors/StepDetector.kt`, `sensors/PdrTracker.kt`)

> ⚠ Código entregado el 2026-10-10, **sin compilar ni probar en dispositivo** por quien lo escribió.
> Confirmar y quitar este aviso.

Es el **único** sitio que calcula la posición a partir de pasos y rumbo (2.3). El mapa público lo usa
a través de `map/MapaPublicoScreen.kt`; la recolección (7.4, ya lo usa desde `RecoleccionViewModel`) y la navegación (6.5) deben usar el mismo
`PdrTracker` en vez de volver a calcular nada en JavaScript.

| Pieza | Firma | Qué hace / cuidado |
|---|---|---|
| `PdrEngine` | `PdrEngine(longitudPasoM = LONGITUD_PASO_DEFECTO_M, ventanaRumbo = 6, ventanaVelocidadMs = 5000)` · `companion { const val LONGITUD_PASO_DEFECTO_M = 0.72 }` | Lógica pura, sin Android (se puede probar con tests unitarios). Propiedades de lectura: `lat`, `lng` (`Double?`), `rumbo`, `pasos`, `distanciaMetros`, `velocidadMps`. |
| `PdrEngine.fijarPosicion` | `(lat, lng)` | Fija el punto de partida y la posición actual. **No** reinicia `pasos`. |
| `PdrEngine.reiniciar` | `()` | Pasos y velocidad a 0 y vuelve al punto de partida. |
| `PdrEngine.onRumboSensor` | `(grados: Float)` | Promedio circular de las últimas 6 lecturas (359° y 1° dan 0°, no 180°). |
| `PdrEngine.fijarRumboManual` | `(grados: Float)` | Rumbo directo, sin promedio (rueda manual). |
| `PdrEngine.onPaso` | `(tMs: Long): Boolean` | Avanza `longitudPasoM` hacia `rumbo`; devuelve `false` si aún no hay posición inicial. Velocidad: pasos de los últimos 5 s (n − 1 intervalos). |
| `StepDetector` | `procesar(x, y, z, tMs, detectar = true): Boolean` · `ultimaDesviacion` · `reiniciar()` | **Fuente única de pasos.** Magnitud − gravedad **con signo**, filtro pasa-bajos (`FILTRO` 0,5) y cuenta el paso en el **flanco de subida** del pico (latencia ~50–100 ms), con histéresis (rearma por debajo del 60 % del umbral) y pausa mínima `PAUSA_MS` = 250 ms. **Umbral adaptativo:** `FACTOR_UMBRAL` (0,5) × el pico típico reciente (media móvil, `PESO_PICO` 0,3, picos recortados a `PICO_MAX` 8), limitado a `UMBRAL_MIN` 1,1 … `UMBRAL_MAX` 4,0 m/s²; arranca en `UMBRAL` = 1,4. Solo cuentan picos positivos. `umbral` (lectura) da el valor vigente; `ultimaDesviacion` es `|filtrada|` para la gráfica; `detectar = false` solo la actualiza. Probado con una réplica en Python (no con el Kotlin): ~100 % de pasos en caminata normal, ~85–95 % en caminata muy suave, 0 pasos falsos quieto o con temblor de mano. `StepDetectorTest` (JUnit4, **no ejecutado en Gradle**) |
| `PdrTracker` | `PdrTracker(context, longitudPasoM: Double = CalibracionPasoRepository(context).longitudPasoM())` | Une los sensores de Android con `PdrEngine`. Todo en el **hilo principal**. La longitud de paso (calibrada en 7.3b, o 0,72 m) se lee **una sola vez al crearlo**: recalibrar no cambia un tracker ya vivo. ⚠ `sensors` depende ahora de `data.repository` (alternativa: que la pantalla inyecte la longitud). |
| `PdrTracker` (control) | `fijarPosicion(lat, lng)` · `fijarRumboManual(grados)` · `reiniciar()` · `iniciar()` · `detener()` · `liberar()` | Orden típico: `fijarPosicion` → `iniciar` → `detener` / `liberar` al salir. |
| `PdrTracker.estado` | `StateFlow<PdrEstado>` | `lat`, `lng`, `rumboGrados`, `pasos`, `distanciaMetros`, `velocidadMps`, `activo`, `fuentePasos` (`FuentePasos`: `NINGUNA`, `ACELEROMETRO` y `ACELEROMETRO_SIN_SENSOR` si no hay acelerómetro; `HARDWARE` y `ACELEROMETRO_SIN_PERMISO` ya no se asignan y quedan solo por compatibilidad). ⚠ Se añadió `ACELEROMETRO`: un `when` exhaustivo sobre `FuentePasos` en otros archivos dejaría de compilar. |
| `PdrTracker.eventos` | `SharedFlow<PdrEvento>` | Avisos de una sola vez, en cada `iniciar()`: `Brujula(disponible)` y `PasosPorAcelerometro("no_sensor")` (solo si no hay acelerómetro; ya no se emite `permission_denied`). |
| `PdrTracker.onAceleracion` | `((Float) -> Unit)?` | Desviación de la aceleración (m/s²), ~20 Hz, solo para gráficas. |

Receta (Compose):

```kotlin
val tracker = remember { PdrTracker(ctx) }
DisposableEffect(Unit) { onDispose { tracker.liberar() } }
tracker.fijarPosicion(lat, lng)   // antes de iniciar
tracker.iniciar()
val e by tracker.estado.collectAsStateWithLifecycle()   // e.lat, e.lng, e.rumboGrados, e.pasos…
```

Cuidados:
- **La posición no depende de la velocidad ni de la aceleración:** es `pasos × longitud de paso` (la calibrada en 7.3b, o 0,72 m
  por defecto) en dirección del rumbo. La velocidad solo es informativa y el acelerómetro solo detecta pasos (si no hay sensor de
  hardware) y alimenta la gráfica.
- **Pasos:** siempre `StepDetector` sobre el acelerómetro (`SENSOR_DELAY_GAME`, ~50 Hz), sin permiso. `TYPE_STEP_DETECTOR`
  se descartó (2026-10-12): confirma una secuencia antes de avisar y tardaba 1–3 s. El acelerómetro corre mientras el
  rastreo está activo y alimenta a la vez los pasos y la gráfica.
- **Rumbo:** `TYPE_ROTATION_VECTOR` + declinación magnética (`GeomagneticField`) calculada con la
  posición en `fijarPosicion` / `iniciar` (sin posición, la declinación es 0). Elige el eje según la
  postura: celular plano (|`R[8]`| > 0,7) usa la parte superior del celular; en vertical, la cámara
  trasera. Cerca de ~45° de inclinación puede haber un salto. ⚠ **Es una segunda fuente de rumbo**,
  distinta de `EscucharOrientacion` (acimut −180…180, magnético, solo vertical): no mezclarlas.
- `iniciar()` evalúa brújula y pasos **cada vez**; `detener()` no borra la posición. `reiniciar()` sí
  vuelve al punto de partida.
- `eventos` es un `SharedFlow` sin repetición: si nadie recoge en ese instante, el aviso se pierde
  (`MapaPublicoScreen` lo recoge antes de que el usuario pueda pulsar ▶).
- `rumboGrados` vale 0 hasta la primera lectura: filtrar por `activo` antes de mostrarlo.
- Los sensores no siguen el ciclo de vida: solo se liberan en `liberar()` (⚠ siguen activos en
  segundo plano). `RecoleccionViewModel` lo resuelve para 7.4: la pausa llama a `tracker.detener()` y la pantalla pausa sola en `ON_STOP` (ver «Flujo de captura de la recolección»).
- **Longitud de paso (7.3b):** `RecoleccionViewModel` y `MapaPublicoScreen` crean `PdrTracker(app)` sin argumentos y recogen la longitud calibrada
  sin cambios. `distanciaMetros` es `pasos × longitud`, así que el disparador por distancia de 7.4 dispara cada ≈ `metros / longitud` pasos.
  La calibración usa **su propio** `PdrTracker` (`CalibracionViewModel`): si otra pantalla dejara uno sin liberar, habría dos escuchando sensores.
- ⚠ `app.js` repite un umbral fijo de 2,2 (`accelThreshold`) solo para dibujar la línea de la gráfica; el detector ahora usa
  un umbral **adaptativo** que arranca en `StepDetector.UMBRAL` (1,4), así que la línea ya no coincide. Cambiar el valor de `app.js`
  a 1,4 (o enviar el umbral vigente desde Kotlin).

#### Sensores y cámara (`sensors/OrientationProvider.kt`, `camera/CapturaFoto.kt`)

| Pieza | Firma | Qué hace / cuidado |
|---|---|---|
| `tieneSensorRotacion` | `(ctx: Context): Boolean` | ¿El teléfono tiene `TYPE_ROTATION_VECTOR`? Llamarla **antes** de depender de la orientación. |
| `EscucharOrientacion` | `@Composable (activo: Boolean, onOrientacion: (acimutGrados: Float, cabeceoGrados: Float) -> Unit)` | Registra el sensor mientras `activo` sea `true` y lo libera al pasar a `false` o al salir de la composición. Entrega **acimut** (hacia dónde apunta la cámara trasera; 0° = norte **magnético**) y **cabeceo** (≈0° con el celular derecho). Callback en el hilo principal, ~50 Hz (`SENSOR_DELAY_GAME`). |
| `crearImageCapture` | `(): ImageCapture` | `ImageCapture` en modo `MINIMIZE_LATENCY`. Se enlaza al ciclo de vida junto con la vista previa mediante `VistaCamara` (ver 11.5); sin ese enlace `tomarFoto` falla. |
| `crearCarpetaEscaneo` | `(ctx, mantener: Int = 20): File` | Crea `files/camera/photos/<yyyy-MM-dd_HH-mm-ss>/` y **borra las carpetas más antiguas** de `camera/photos/`, dejando solo las últimas `mantener` (contando la nueva). |
| `ImageCapture.tomarFoto` | `(ctx, carpeta: File, prefijo = "foto", onGuardada: (File) -> Unit, onFallo: () -> Unit)` | Guarda `<prefijo>_<n>.jpg` (n = primer número libre desde 1). Los callbacks llegan en el hilo principal. Si falla, borra el archivo reservado y llama a `onFallo` (también si `takePicture` lanza excepción, p. ej. cámara aún no enlazada; en ese caso `onFallo` se llama **de forma síncrona**). |
| `liberarCamara` | `(ctx)` | `ProcessCameraProvider.unbindAll()`; si falla solo deja un `AppLog.w`. |

Cuidados:
- **El acimut sale en −180…180, no en 0…360** (viene de `getOrientation`, aunque el comentario del archivo diga que "crece hacia la derecha"). Normalizar con `(x + 360) % 360` antes de compararlo con rumbos o con `Foto.rumbo`. Es norte **magnético**, no geográfico.
- `EscucharOrientacion` **no avisa si no hay sensor**: simplemente no llama nunca al callback. Verificar con `tieneSensorRotacion`. Ignora la precisión del sensor (no hay aviso de "calibrar").
- Los ejes están remapeados para el celular **en vertical**; en horizontal el acimut y el cabeceo no sirven.
- Solo se puede usar dentro de una composición (no desde un ViewModel). No sigue el ciclo de vida de la Activity: pasar `activo = false` en `ON_STOP`, o el sensor sigue escuchando en segundo plano (`EscaneoScreen` hoy no lo hace). Para el seguimiento híbrido (2.3), que corre fuera de una pantalla, haría falta una versión con `Flow`.
- **`crearCarpetaEscaneo` es destructiva.** Si la recolección (7.4) reutiliza `camera/photos/`, sus carpetas se borrarán tras 20 escaneos. Usar otra raíz o un `mantener` distinto. La recolección guarda en `files/recoleccion/` (11.6) y no la toca.
- **Las fotos no llevan metadatos.** `tomarFoto` solo escribe el JPG: la posición (`lat`, `lng`) y el `rumbo` hay que guardarlos aparte (el `manifest.json` los exige, ver 11.6). Los archivos quedan en `filesDir` (privados de la app, no visibles en la galería del teléfono) y se llaman `foto_1.jpg`, no `0001.jpg`: la recolección debe asignar el `id` de `Foto` por su cuenta.
- `onFallo` no trae el motivo; el código de error de CameraX solo queda en el log (`Camara`).
- `liberarCamara` desenlaza **todos** los casos de uso del proceso y espera el `Future` en el hilo que la llama: llamarla al salir de la vista de cámara, no mientras otra vista aún la usa.

#### Flujo de captura del escaneo (`ui/ubicacion/EscaneoViewModel.kt`)

Es lo que la recolección (7.4) querrá imitar: gira → foto cada cierto ángulo → feedback. Verificado:

| Pieza | Detalle |
|---|---|
| Creación | `EscaneoViewModel(app: Application) : AndroidViewModel`. Crea él mismo `EscaneoBackendStub`, `VoiceController(app)` y `FeedbackCaptura(app)`. |
| Salidas | `estado: StateFlow<EscaneoUiState>` y `eventos: SharedFlow<EscaneoEvento>` (buffer 4). Eventos vistos: `Capturar` (la pantalla debe llamar a `tomarFoto`) y `Completado`. |
| Entradas (las llama la pantalla) | `iniciar()` · `cancelar()` · `sensorNoDisponible()` · `onOrientacion(acimut, cabeceo)` (~50 Hz) · `onFotoTomada(File)` · `onFotoFallida()` |
| Fases | `PREPARANDO` (instrucciones habladas) → `ESCANEANDO` → `ANALIZANDO` → evento `Completado`; o `ERROR`. Errores: `SIN_SENSOR`, `VUELTA_INCOMPLETA`, `TIEMPO_AGOTADO`, `SIN_CONEXION` (cada uno con `.mensaje`, que se dice por voz). Instrucciones en vivo: `VERTICAL` > `MAS_DESPACIO` > `GIRAR`. |
| ¿Cuándo pide foto? | Si **todo** se cumple: no hay captura en curso, no está en pausa, el cabeceo está dentro de `INCLINACION_MAX`, la velocidad suavizada no supera `VELOCIDAD_MAX`, faltan fotos y el progreso llegó a `fotos × GRADOS_POR_FOTO` (72°). |
| Seguimiento del giro | Diferencia de acimut entre lecturas, normalizada a (−180°, 180°] para cruzar 359°→0°. Velocidad con media móvil exponencial (0,85 / 0,15). El progreso se limita a 0…360°. |
| Voz | `iniciar()` habla las instrucciones y, al terminar, pasa a `ESCANEANDO` **si la fase sigue siendo `PREPARANDO`** (no usa token). Los avisos de inclinación y velocidad se limitan con `AVISO_CADA_MS`; `fallar()` y `analizar()` hablan sin ese límite. Recordar que `speak` corta lo anterior (11.2). |
| Fallos | `onFotoFallida()` pausa 1 s y deja que se reintente solo (sin límite de intentos). Sin avance durante `INACTIVIDAD_MS` → `VUELTA_INCOMPLETA`. Backend: `withTimeout(TIMEOUT_BACKEND_MS)`; el tiempo agotado va **antes** que `CancellationException` en el `catch` porque es subclase suya. |

Cuidados:
- ⚠ **Girar a la izquierda resta progreso.** El comentario del código dice que solo cuenta el giro a la derecha, pero el progreso suma `delta` **con signo** (baja hasta 0). Lo que sí exige ir a la derecha es el reinicio del contador de inactividad (`delta > 0,2°`).
- La normalización de `delta` ya asume que el acimut llega en −180…180 (confirma la nota de `EscucharOrientacion`).
- **`CONSERVAR_FOTOS = true`** (constante privada del archivo): las fotos **no se borran** al cancelar, reiniciar ni destruir el ViewModel. Debe pasar a `false` antes de publicar (decisión abierta 12). Aun así, una foto que llega fuera de la fase `ESCANEANDO` **no se cuenta y nunca se borra**, ni siquiera con `false`.
- Las excepciones inesperadas del backend se informan como `SIN_CONEXION` (puede disfrazar otros errores).
- `EscaneoEvento.Completado` **no lleva datos** y `backend.analizar` devuelve `Unit`: antes de 6.3 hay que decidir qué entrega (posición estimada) y por dónde viaja (11.8).
- La detección de inactividad solo se evalúa dentro de `onOrientacion`: si el sensor deja de emitir, no hay tiempo límite.
- ⚠ Carrera teórica confirmada: `cancelar()` deja `EscaneoUiState()` con `fase = PREPARANDO`; si un `alTerminar` de `iniciar()` ya estaba encolado, pasaría a `ESCANEANDO` tras cancelar. En la práctica es inofensiva porque `EscaneoScreen` llama a `onCancelar()` justo después y el ViewModel se destruye, pero un flujo nuevo que cancele **sin salir** de la pantalla debe protegerse (por ejemplo con el token de 11.2).
- **Una foto de `Capturar` perdida deja el escaneo atascado.** `eventos` es un `SharedFlow` sin repetición: un evento emitido mientras no hay colector (p. ej. durante una rotación) se pierde. Si es `Capturar`, `capturando` queda en `true` y no se pide otra foto hasta que salte `VUELTA_INCOMPLETA` (20 s). Si es `Completado`, la pantalla se queda en "Analizando…".
- **El acimut de cada foto no se guarda.** El ViewModel lo escribe en el log al pedir la foto pero no lo asocia al archivo, y el contrato `EscaneoBackend.analizar(fotos: List<File>)` solo recibe archivos: el TODO del backend (enviar el *heading* de cada foto, §2.1) obliga a cambiar ambos.
- Todo el cálculo del giro (`onOrientacion`) es **privado** del ViewModel: la recolección no puede reutilizarlo. Candidato a extraer como caso de uso puro (11.7) que reciba `(acimut, cabeceo, instante)` y devuelva progreso, velocidad y qué instrucción dar.

**Parámetros (`EscaneoConfig`, `ui/ubicacion/EscaneoConfig.kt`, `internal object`; verificados):**

| Constante | Valor | Significado |
|---|---|---|
| `TOTAL_FOTOS` | 5 | Fotos por vuelta, a 0°, 72°, 144°, 216° y 288° **medidos desde donde empezó el giro** |
| `GRADOS_POR_FOTO` | 72° | `360 / TOTAL_FOTOS` |
| `VELOCIDAD_MAX` | 45 °/s | Por encima se pide "Más despacio" y no se toman fotos |
| `INCLINACION_MAX` | 20° | Desvío máximo del cabeceo respecto a la vertical |
| `INACTIVIDAD_MS` | 20 000 | Sin avanzar este tiempo → `VUELTA_INCOMPLETA` |
| `AVISO_CADA_MS` | 4 000 | Mínimo entre avisos hablados de inclinación/velocidad |
| `TIMEOUT_BACKEND_MS` | 30 000 | Espera máxima al backend → `TIEMPO_AGOTADO` |

**Estado y eventos (`ui/ubicacion/EscaneoState.kt`; verificado):**
- `Fase`: solo `PREPARANDO`, `ESCANEANDO`, `ANALIZANDO` y `ERROR` (no hay una fase "completado": el final es el evento).
- `EscaneoUiState(fase = PREPARANDO, progreso = 0f, fotos = 0, inclinacionOk = true, instruccion = GIRAR, error = null)`; `progreso` en grados girados 0…360.
- Textos: `Instruccion.GIRAR` "Gira lentamente\nhacia la derecha" (lleva salto de línea), `MAS_DESPACIO` "Más despacio", `VERTICAL` "Mantén el celular vertical". `ErrorEscaneo`: `SIN_CONEXION` "Sin conexión con el servidor", `TIEMPO_AGOTADO` "El análisis tardó demasiado", `VUELTA_INCOMPLETA` "No completaste la vuelta", `SIN_SENSOR` "Este teléfono no tiene sensor de giro".
- `EscaneoEvento` (`sealed interface`): `Capturar` (la pantalla es dueña de CameraX) y `Completado` ("hay que navegar al Resultado").

**Contrato del backend (`ui/ubicacion/EscaneoBackend.kt`; verificado):** `interface EscaneoBackend { @Throws(IOException::class) suspend fun analizar(fotos: List<File>) }` (devuelve `Unit`). `EscaneoBackendStub` espera 2,5 s y no hace nada. ⚠ No sigue la convención de 11.6 (`interface XRepository` en `data/repository/`) y el ViewModel lo instancia directamente (`private val backend = EscaneoBackendStub`), así que cambiarlo exige editar el ViewModel.

**Cómo lo conecta `EscaneoScreen` (verificado):**
- Firma: `EscaneoScreen(onCancelar, onCompletado, onAjustes = {}, viewModel = viewModel())`. ⚠ **`AppNav` no pasa `onAjustes`**: el botón de ajustes de esta vista no hace nada hoy.
- **Comprueba el permiso de cámara por su cuenta** (`checkSelfPermission`; si falta, lo pide con `RequestPermission`), aunque la ruta ya usa `PedirPermisos`. Si se niega, muestra "Necesito permiso de cámara" y no hay forma de reintentar sin salir.
- Con cámara concedida: si hay sensor llama a `nuevoEscaneo()` (abre una carpeta nueva con `crearCarpetaEscaneo(ctx)` y llama a `viewModel.iniciar()`); si no, `viewModel.sensorNoDisponible()`. **"Repetir" abre otra carpeta**, así que cada intento cuenta para el límite de 20 de `crearCarpetaEscaneo`.
- `EscucharOrientacion(activo = camaraOk && tieneSensor, onOrientacion = viewModel::onOrientacion)`: el sensor escucha **todo el tiempo que la pantalla esté en composición**, también en `PREPARANDO`, `ANALIZANDO` y `ERROR` (el ViewModel descarta las lecturas fuera de `ESCANEANDO`). ⚠ **Escaneo no maneja `ON_STOP`**: si la app pasa a segundo plano a mitad de vuelta, el sensor y la voz siguen.
- Eventos en un `LaunchedEffect(Unit)`: `Capturar` → `imageCapture.tomarFoto(ctx, carpeta, prefijo = "escaneo", onGuardada = viewModel::onFotoTomada, onFallo = viewModel::onFotoFallida)` (los archivos se llaman `escaneo_1.jpg`…); `Completado` → `onCompletado()`.
- `DisposableEffect`: mantiene la pantalla encendida (`keepScreenOn`) y, al salir, **llama a `liberarCamara(ctx)`**: ese es el sitio donde se libera la cámara (11.5, `VistaCamara`).
- Cancelar (botón, flecha o atrás del sistema) = `viewModel.cancelar()` + `onCancelar()`.
- Título principal según prioridad: sin cámara → "Necesito permiso de cámara"; `ANALIZANDO` → "Analizando…"; `ERROR` → el mensaje del error; si no, el texto de la instrucción.
- Patrón 11.1: `EscaneoContent` es `private` y **no tiene `@Preview`**; para previsualizarlo habría que volverlo `internal`.

#### Flujo de captura de la recolección (`ui/admin/recoleccion/RecoleccionViewModel.kt`, `domain/usecase/DisparadorCaptura.kt`)

Imita el flujo del escaneo (arriba), pero la foto se dispara por **distancia o tiempo** y no por ángulo. El ViewModel es dueño del
PDR (sobrevive a rotar la pantalla); la **pantalla es dueña de CameraX** (11.5).

| Pieza | Detalle |
|---|---|
| `DisparadorCaptura` | Lógica pura, sin Android. `debeCapturar(distanciaTotalM, ahoraMs): Boolean` · `alCapturar(distanciaTotalM, ahoraMs)` (solo si la foto **se guardó**) · `cambiarModo(ModoCaptura)` · `alReanudar(ahoraMs)` · `reiniciar()` · `modo` (lectura) |
| `ModoCaptura` | `PorDistancia(metros)` y `PorTiempo(segundos)`; `OPCIONES` (3, 5 y 10 m; 3 y 5 s), `POR_DEFECTO` (cada 5 m) y `etiqueta` |
| `Deriva.estimar(distanciaDesdeAnclaM)` | Devuelve `EstimacionDeriva(derivaM, precisionM, nivel)`. **Heurística provisional:** deriva = 4 % de la distancia desde el último ancla (decisión 16). `NivelCalidad`: `ALTA` (< 15 m), `MEDIA` (< 30 m), `BAJA` |
| `RecoleccionViewModel(app)` | `AndroidViewModel` **sin `Factory`**: crea `RecoleccionRepositoryLocal`, `PdrTracker`, `FeedbackCaptura` y `DisparadorCaptura`. Salidas: `ui: StateFlow<RecoleccionUiState>`, `eventos: Flow<RecoleccionEvento>` (`Channel(BUFFERED)`, un solo colector: `Capturar`, `Finalizado(resumen)`, `Descartado`) y `carpetaFotos(): File?` (`null` antes de crear el video) |

Entradas del ViewModel (las llama la pantalla): `alAbrir()` (idempotente: consume `SesionDeRecoleccion.inicio`, crea el video, arranca el PDR; sin inicio, `error = SIN_INICIO`) · `onFotoTomada(File)` / `onFotoFallida()` · `alAlternarPausa()` · `alIrASegundoPlano()` · `alCambiarModo(ModoCaptura)` · `alReubicarse()`, `alMoverReanclaje(lat, lng)`, `alConfirmarReanclaje()`, `alCancelarReanclaje()` · `alAgregarAlerta()`, `alActualizarAlerta(a)`, `alGuardarAlerta()`, `alCancelarAlerta()` · `alPedirFinalizar()`, `alConfirmarFinalizar()`, `alCancelarFinalizar()` · `descartarAviso()`.

`RecoleccionUiState` (`RecoleccionState.kt`): `fase` (`INICIANDO`, `GRABANDO`, `PAUSADA`, `FINALIZANDO`), `error`, `nombreVideo`, `lat` / `lng` (`Double?`), `rumbo` (0…360), `fotosTomadas`, `distanciaMetros`, `pasos`, `duracionSegundos`, `deriva`, `modo`, `destelloCaptura` (contador: la UI parpadea cuando sube), `avisos` (`AvisoRecoleccion`: foto borrosa, poca luz, batería baja, almacenamiento bajo), `aviso` (texto temporal), `fotosJson`, `trayectoriaJson`, `alertasJson`, `alertasActivas`, `reanclaje`, `confirmandoFinalizar`, `formularioAlerta`, `errorAlerta`; calculadas `reubicando`, `enCurso` y `llegoAlMaximo`. Constante pública `MAX_FOTOS_VIDEO = 200`.

Comportamiento:
- **Primera foto inmediata**; luego `debeCapturar`. Solo captura en `GRABANDO`, sin otra captura en curso, sin re-anclaje abierto y con menos de 200 fotos.
- **Foto fallida:** no se llama a `alCapturar`, así que `debeCapturar` seguiría en `true`; el ViewModel pone una **pausa de capturas** (1 s; 5 s tras 5 fallos seguidos), como `EscaneoViewModel.onFotoFallida`.
- **Archivo:** `tomarFoto(ctx, carpetaFotos(), "tmp", …)`; `onFotoTomada` llama a `repo.registrarFoto`, que **renombra** el JPG a `NNNN.jpg` y lo anota en el manifest con la posición y el rumbo del PDR (las fotos no llevan metadatos, ver arriba).
- **Pausa** detiene el PDR (`tracker.detener()`); `alIrASegundoPlano()` (la pantalla lo llama en `ON_STOP`) pausa sola.
- **Re-anclaje manual:** `tracker.fijarPosicion` + desplazamiento **uniforme** de fotos (`repo.desplazarFotos`) y trayectoria desde el último ancla; reinicia la deriva y frena las capturas mientras `reanclaje != null`.
- **Reloj:** tiempo de grabación sin contar pausas (`elapsedRealtime`). Cada 30 s revisa la batería (aviso con ≤ 15 % y sin cargar) y el almacenamiento (aviso con < 200 MB; pausa sola con < 50 MB).
- **Finalizar:** con 0 fotos el video se **borra** (`repo.descartar`) y se emite `Descartado`; si no, `repo.finalizar` y `Finalizado(resumen)`.
- **Trayectoria:** un punto cada 3 pasos (`trayectoriaJson`).
- **Distancia:** `pasos × longitud de paso` del `PdrTracker` (calibrada en 7.3b, leída una vez al crearlo en `alAbrir`; 0,72 m si nunca se calibró).

Cuidados:
- Una foto que se está guardando en el instante del re-anclaje puede quedar con la coordenada vieja.
- La brújula del PDR depende de la declinación magnética calculada al fijar la posición.
- `validarMensajeAlerta` **duplica** la regla de `EditorMapaViewModel` (11.5 pide extraerla).
- Foto borrosa y poca luz nunca se activan (control de calidad desactivado).
- Sin retomar tras matar el proceso (`buscarEnCurso()` existe, pero no se usa).

### 11.3 Permisos y sesión

**Sesión (`SessionManager`, `session/SessionManager.kt`)**

| Pieza | Firma | Qué hace / cuidado |
|---|---|---|
| Constructor | `SessionManager(context: Context)` | Guarda en `EncryptedSharedPreferences` (archivo `campus_session`, llaves AES256-SIV, valores AES256-GCM, llave maestra en Android Keystore). El almacén se crea **de forma perezosa** en el primer uso: ese primer acceso puede tardar y puede lanzar excepción si el Keystore falla (p. ej. tras restaurar una copia de seguridad). Usa `applicationContext`, así que no filtra la `Activity`. |
| `guardar(sesion: Sesion)` | `Unit` | Escribe token, id, nombre, correo y rol (`apply`, asíncrono). |
| `obtener()` | `Sesion?` | `null` si no hay token **o** el rol guardado no es válido. Si faltan id, nombre o correo, los devuelve como `""`. **No comprueba caducidad del token.** |
| `esAdmin()` | `Boolean` | `obtener()?.usuario?.rol == Rol.ADMIN`. Lee y descifra toda la sesión en cada llamada: guardar el resultado en el ViewModel en vez de llamarlo en cada recomposición. |
| `cerrarSesion()` | `Unit` | `clear()` de todo el archivo: borra token y datos del usuario. |

- Quién lo usa (el Panel admin está verificado en `PanelAdminViewModel`, ver 11.5; Login verificado en `LoginViewModel`, ver 11.5): Login guarda la sesión de un `ADMIN` y, si ya existe una, entra directo al panel; el Panel admin lee nombre y rol, cierra sesión y usa `onSinSesion`. Un usuario que no es `ADMIN` **no se guarda**.
- ⚠ Cada `SessionManager(context)` crea su propia instancia de `EncryptedSharedPreferences`: crear **una por ViewModel**, no una por pantalla ni por recomposición. `MyApp` **no guarda ninguna instancia compartida** (solo crea una para limpiar la sesión al arrancar).
- ⚠ **La sesión se borra en cada arranque en frío.** `MyApp.onCreate` llama a `SessionManager(this).cerrarSesion()` (decisión de producto: "el admin debe iniciar sesión cada vez que se abre la app desde cero"; si falla solo deja un `AppLog.e`). Consecuencias: la sesión **solo sobrevive mientras el proceso siga vivo**; si Android mata la app en segundo plano (p. ej. en una recolección larga), al volver no habrá sesión y el panel dispara `onSinSesion`. Cualquier flujo largo del admin debe tolerarlo.
- Nunca registrar el token en `AppLog`.
- Verificado en `LoginViewModel`: `session.esAdmin()` se llama en su `init`, en el hilo principal y **sin `try/catch`**: si el Keystore falla, crear el ViewModel lanza excepción y Login no abre (11.5).

**Permisos**

| Pieza | Ubicación | Cómo se usa | Cuidado |
|---|---|---|---|
| `Permisos` | `MainActivity.kt` (`object`) | `Permisos.CAMARA`, `Permisos.MICROFONO`, `Permisos.INICIALES: Array<String>`, `Permisos.ACTIVIDAD: Array<String>` | Verificado. `INICIALES` = cámara + micrófono + `ACTIVITY_RECOGNITION` (esta última **solo desde Android 10**; en versiones anteriores no se pide). Se piden en un solo diálogo al abrir Inicio, una vez por entrada de navegación (bandera `rememberSaveable`), y Inicio se muestra aunque se niegue alguno. `ACTIVIDAD` = solo `ACTIVITY_RECOGNITION` desde Android 10 (lista **vacía** antes: `PedirPermisos` llama entonces a `onResultado(true)` sin diálogo); la usa la ruta `admin/calibracion`. |
| `PedirPermisos(permisos: Array<String>, onResultado: (todosConcedidos: Boolean) -> Unit)` | `MainActivity.kt` | Se pone en la **ruta**, antes de la pantalla: si ya están concedidos llama a `onResultado(true)` sin mostrar nada (ver la ruta `ubicarme`). | Verificado. Al entrar comprueba `checkSelfPermission` y lanza el diálogo **solo con los que faltan**; el resultado es `true` si todos **los pedidos** se concedieron. Se llama desde un `LaunchedEffect(Unit)`, es decir, **después** de la primera composición (no dibujar nada que dependa del resultado antes). No explica por qué se pide ni abre Ajustes si el permiso quedó negado de forma permanente: en ese caso el diálogo ni aparece y `onResultado(false)` llega al instante. En `ubicarme`, si se niega la cámara la ruta hace `popBackStack()` **sin mostrar ningún mensaje**. En la ruta `inicio` el resultado se **ignora** (se marca `permisosPedidos = true` sea cual sea) y, mientras sale el diálogo, no se dibuja nada. |
| Ayudas de Inicio (`permisosNecesarios`, `permisosFaltantes`, `BannerPermisos`, `abrirAjustesApp`) | `ui/inicio/InicioScreen.kt` | — | Verificado. Son `private`: **no** se pueden reutilizar. Candidato a extraer a `ui/components/`. `permisosNecesarios()` **repite** la lista de `Permisos.INICIALES` y la pantalla pide los permisos por su cuenta además de la ruta (⚠ ver Inicio en 11.5). |
| Comprobación de cámara en Escaneo | `EscaneoScreen.kt` | `checkSelfPermission(CAMERA)` y, si falta, `RequestPermission` | **Duplica** lo que ya hace `PedirPermisos` en la ruta `ubicarme`; sirve de red de seguridad. Si se niega muestra "Necesito permiso de cámara" sin opción de reintento. |
| Comprobación de micrófono en Destino | `SeleccionDestinoScreen.kt` | `checkSelfPermission(RECORD_AUDIO)` sin volver a pedirlo; si falta, `BannerEstado` y la vista sigue solo con toques. Verificado: se comprueba **una sola vez** (`remember`) y `alAbrir` ignora llamadas repetidas, así que conceder el micrófono después (p. ej. desde Ajustes) no se nota hasta que se recree el ViewModel. Inicio y Destino usan `Manifest.permission.*` directamente, no `Permisos`. | Mismo criterio que pide la sección 4 ("sin micrófono: solo botones"). |

### 11.4 Tema y colores

`CampusColors` (`ui/theme/CampusColors.kt`) es la paleta para **toda vista nueva**. Verificado contra el código: es un `object` público de `Color` de Compose y sus 11 valores son exactamente los de esta tabla (ninguno más):

| Token | Valor | Uso típico |
|---|---|---|
| `Fondo` | `#030615` | Fondo de pantalla |
| `Superficie` / `SuperficieAlta` | `#050B24` / `#0B1235` | Tarjetas / elementos sobre tarjetas |
| `Borde` | `#232E78` | Borde fino de tarjetas y chips |
| `Primario` / `Acento` | `#5B3CF5` / `#8B6BFF` | Botones principales / íconos y resaltes |
| `TextoPrincipal` / `TextoSecundario` / `TextoSuave` | `#FFFFFF` / `#B9B2FF` / `#A9B0D9` | Jerarquía de texto |
| `Exito` / `Peligro` | `#2EE887` / `#B84DFF` | Estados |

⚠ Hay paletas privadas que **no** vienen de aquí: `Inicio` (`private val Fondo = #030712`, `Morado`…),
`EscaneoColores` y `GaleriaColores`. Se migran a `CampusColors` cuando se toque cada vista. Tampoco viene de aquí el fondo del `WebView` del editor de mapa (`#0A0E1A`, el mismo de su página web; no es `Fondo` `#030615`): al migrar esa página a la paleta hay que cambiar ambos sitios (el overlay `NoEncontrado` de Detalle de video usa el mismo `#0A0E1A`). `PanelAdminScreen` sí usa `CampusColors` (con el alias `C`), pero con literales propios: `#0C1340` (avatar y círculos de íconos) y el degradado `#3F24C4` → `#241470` de la tarjeta destacada. Las páginas web de los mapas llevan su propia paleta en CSS (fondo `#0A0E1A`, trazo de ruta `#6366f1`, prioridad alta `#ef4444`, normal `#f59e0b`): ahí la prioridad alta es **roja**, mientras `CampusColors.Peligro` es morado.

**`EscaneoColores`** (`ui/ubicacion/EscaneoConfig.kt`) es un `internal object` (no `private`: se ve en todo el módulo, pero no debe usarse en vistas nuevas). Equivalencias aproximadas al migrar a `CampusColors`:

| `EscaneoColores` | Valor | Más parecido en `CampusColors` | Ojo al migrar |
|---|---|---|---|
| `Fondo` | `#030712` | `Fondo` `#030615` | Casi igual |
| `Panel` | `#0B1220` | `Superficie` `#050B24` / `SuperficieAlta` `#0B1235` | Elegir según la altura de la tarjeta |
| `Morado` / `MoradoBoton` | `#7C3AED` / `#6D4AFF` | `Primario` `#5B3CF5` | Un solo primario reemplaza a los dos |
| `MoradoClaro` | `#A78BFA` | `Acento` `#8B6BFF` | |
| `TextoSecundario` | `#9CA3AF` (gris) | `TextoSuave` `#A9B0D9` | `CampusColors.TextoSecundario` es **lila** (`#B9B2FF`), no gris |
| `Verde` | `#22E58B` | `Exito` `#2EE887` | Casi igual |
| `Rojo` | `#EF4444` | `Peligro` `#B84DFF` | ⚠ **`Peligro` es morado, no rojo**: migrar cambia el color de los errores |
| `Pista` | `#2A2F45` | `Borde` `#232E78` | Distinto: `Pista` es gris azulado |

**Paleta privada de Login** (`ui/auth/LoginScreen.kt`, `private val` sueltos; verificado): `Fondo` `#030615`, `Primario` `#5B3CF5`, `Acento` `#8B6BFF`, `TextoSecundario` `#B9B2FF` y `TextoPrincipal` `#FFFFFF` son **idénticos** a los de `CampusColors`; solo `CampoFondo` `#060C25` (≈ `Superficie` `#050B24`) y `CampoBorde` `#2A3485` (≠ `Borde` `#232E78`, más claro) no tienen equivalente exacto, y el degradado del logo usa `#9A7BFF` → `#5B3CF5`. El comentario del archivo («cuando exista ui/theme, mover aquí…») quedó viejo: ya existe `CampusColors`, y migrar Login es casi solo cambiar el origen de cinco valores. `SeleccionDestinoScreen`, en cambio, **sí** usa `CampusColors` (`Fondo`, `Acento`).

**Paleta privada de Inicio** (`ui/inicio/InicioScreen.kt`, `private val` sueltos; verificado): `Fondo` `#030712`, `Morado` `#7C3AED`, `MoradoClaro` `#C4B5FD`, `MoradoOscuro` `#2E1F8A`, `TextoSecundario` `#9CA3AF` (gris), `Verde` `#22E58B`, `Rojo` `#EF4444`, `FondoAviso` `#3B1D1D`, más literales en línea: divisor `#111827` y degradado del orbe `#5B2FD6` / `#7C45EE`. Son los mismos valores que `EscaneoColores` salvo `MoradoClaro` (aquí `#C4B5FD`, allí `#A78BFA`) y los extras (`MoradoOscuro`, `FondoAviso`, divisor y degradado). Al migrar valen las equivalencias de la tabla anterior, incluido el aviso de que `Peligro` es morado y no rojo.

**`GaleriaColores`** (`ui/admin/imagenes/GaleriaScreen.kt`) es un `internal object`, usado por la Galería y también por `VideosScreen` (otro paquete). Equivalencias aproximadas al migrar (TODO que el propio archivo ya anota):

| `GaleriaColores` | Valor | Más parecido en `CampusColors` | Ojo al migrar |
|---|---|---|---|
| `Fondo` | `#0A0A1E` | `Fondo` `#030615` | Distinto: es un azul-morado más claro |
| `Tarjeta` | `#12122B` | `Superficie` `#050B24` / `SuperficieAlta` `#0B1235` | Elegir según la altura |
| `Placeholder` | `#1C1C3C` | `SuperficieAlta` | Solo el fondo de las miniaturas mientras Coil carga |
| `Borde` | `#3D2F8F` | `Borde` `#232E78` | Más morado y más claro |
| `Primario` | `#7C4DFF` | `Primario` `#5B3CF5` | |
| `Acento` | `#B39DFF` | `TextoSecundario` `#B9B2FF` (por tono) o `Acento` `#8B6BFF` | Aquí `Acento` es lila **claro**; el de `CampusColors` es más oscuro |
| `Texto` | `#FFFFFF` | `TextoPrincipal` | Igual |
| `TextoSuave` | `#B4B4CC` | `TextoSuave` `#A9B0D9` | Casi igual |
| `Verde` | `#2ECC71` | `Exito` `#2EE887` | Parecido |
| `Azul` | `#29B6F6` | — | **No existe equivalente**: marca `SUBIDA` y "Pendiente de proceso" |
| `Rojo` | `#FF5252` | `Peligro` `#B84DFF` | ⚠ **`Peligro` es morado, no rojo**: migrar cambia el color de `ERROR`, "Con errores" y "Eliminar" |

⚠ **`MainActivity` envuelve toda la app en el `MaterialTheme` por defecto** (`MaterialTheme { AppNav() }`),
no en un tema propio con `CampusColors`. Los componentes de Material que no reciben color explícito
(por ejemplo `AlertaFormSheet`, 11.5) salen con los colores estándar de Material; cada vista pública
pinta sus colores a mano. Un tema propio sería el sitio natural para unificar las paletas.

### 11.5 Componentes de UI reutilizables

| Componente | Ubicación | Firma | Para qué / cuidado |
|---|---|---|---|
| `BannerEstado` | `ui/components/BannerEstado.kt` | `BannerEstado(tipo: TipoBanner, icono, titulo, mensaje)` | Aviso de error (`TipoBanner.Error`) o advertencia (`TipoBanner.Advertencia`). TalkBack lo anuncia al aparecer. Usado en Login y Destino. |
| `ZonaMicrofono` | `ui/destino/componentes/PanelesVoz.kt` | `ZonaMicrofono(escuchando: Boolean, onClick: () -> Unit)` | Micrófono grande con halo que pulsa y el texto "Escuchando… / Toca para hablar". Sirve para cualquier vista que escuche. Candidato a `ui/components/`. Verificado contra el código (bache 2); detalle abajo. |
| `TarjetaTextoReconocido` | ídem | `(texto: String, onDescartar: () -> Unit)` | Lo que entendió el reconocimiento, con ✕. |
| `TarjetaConfirmacion` | ídem | `(lugar: LugarDestino, onSi, onNo)` | Específica de lugares; para otra confirmación hay que generalizar el título. Siempre dice «Di sí o no.», incluso sin micrófono. Detalle abajo. |
| `BarraSuperior` | `ui/destino/componentes/PanelesVoz.kt` | `(onAtras, onAjustes)` | Confirmada la duplicación: `ui/ubicacion/componentes/PanelesEscaneo.kt` tiene otra con la misma firma pero con **título fijo** ("Ubicarme" / "Captura de entorno") y colores de `EscaneoColores` (ver abajo). Unificar en `ui/components/` con parámetros `titulo` y `subtitulo`. Verificado (bache 2): esta versión usa `BotonIcono` (56 dp) y título fijo «Destino»; la de Ubicarme usa `IconButton` (48 dp). |
| `BotonIcono` | `ui/destino/componentes/Comun.kt` | `internal` · `(icono, descripcion, onClick, tint)` | Botón circular de solo ícono: área de 56 dp, ícono de 28 dp (`tint` por defecto `Acento`); la descripción va en el contenedor y el ícono no lleva descripción propia. Sin parámetro `enabled`. |
| `Modifier.tarjeta(radio)` | ídem | `internal` | Fondo `Superficie` + borde de 1 dp `Borde` con esquinas redondeadas (`radio` 20 dp por defecto; `FilaLugar` usa 18 dp). Aplica recorte, fondo y borde, en ese orden. |
| `CategoriaLugar.icono()` | ídem | `internal` | Ícono de cada categoría (el dominio no conoce Compose). Verificado: es un `when` **exhaustivo, sin `else`**, así que una categoría nueva no compila hasta que se le asigne ícono. Tabla abajo. |
| `AlertaFormSheet` | `ui/admin/mapa/AlertaFormSheet.kt` (`public`) | `(alerta: Alerta, esNueva: Boolean, error: String?, onCambio: (Alerta) -> Unit, onGuardar, onCancelar, onEliminar)` | Hoja inferior (`ModalBottomSheet`) para crear o editar una alerta (vista 7.9). Detalle abajo. |
| `MapaPublicoScreen` | `map/MapaPublicoScreen.kt` (`public`) | `MapaPublicoScreen(modifier: Modifier = Modifier)` | Mapa público (`index.html` + `app.js`) en un `WebView` con seguimiento por pasos. Crea su propio `PdrTracker`, registra el puente `AndroidBridge` (`PuentePdr`) y empuja la posición, el rumbo y los avisos a la página (tabla en 2.6). Aplica `systemBarsPadding()` (el mapa no maneja *insets*). Libera sensores y `WebView` al salir. Hoy lo aloja `admin/ubicacion-manual` (11.8). |
| `CalibracionScreen` / `CalibracionContent` | `ui/admin/calibracion/CalibracionScreen.kt` (`public`) | `CalibracionScreen(onVolver, modifier, vm = viewModel())` · `CalibracionContent(ui, acciones, modifier)` | Vista 7.3b completa (detalle abajo, «CalibracionScreen y CalibracionBridge»). **No navega.** |
| `UbicacionManualScreen` / `UbicacionManualContent` | `ui/admin/recoleccion/UbicacionManualScreen.kt` (`public`) | `UbicacionManualScreen(onVolver, onConfirmar: (InicioRecoleccion) -> Unit, onAjustes = {}, onCalibrar = {}, viewModel = viewModel(factory = …))` · `UbicacionManualContent(estado, acciones, modifier, longitudCalibradaM: Double? = null)` | Vista 7.3 completa (detalle abajo, «UbicacionManual»). Sustituye a `MapaPublicoScreen` en la ruta `admin/ubicacion-manual`. |
| `EditorMapaScreen` / `EditorMapaContent` | `ui/admin/mapa/EditorMapaScreen.kt` (`public`) | `EditorMapaContent(alertasJson, lugaresJson, pendientes, borradorJson, eventos, modifier, miPosicion)` | Mapa web de alertas dentro de un `WebView` (vista 7.8). Detalle abajo. |
| `FilaCategorias`, `CampoBusqueda`, `EncabezadoLista`, `FilaLugar`, `EstadoVacio`, `BotonVolver` | `ui/destino/componentes/ListaLugares.kt` | `FilaCategorias(seleccionada: CategoriaLugar?, onElegir: (CategoriaLugar?) -> Unit)` · `CampoBusqueda(texto: String, onCambio: (String) -> Unit)` · `EncabezadoLista(orden: OrdenLugares, onCambiarOrden: () -> Unit)` · `FilaLugar(lugar: LugarDestino, onClick: () -> Unit)` · `EstadoVacio(mensaje: String?, accion: String, onAccion: () -> Unit)` · `BotonVolver(onClick: () -> Unit)` | Verificado contra el código (bache 2). Propios de Destino salvo `EstadoVacio` y `BotonVolver`, que son genéricos. Todos públicos; `ChipCategoria` es privado. Detalle abajo. |
| `EncabezadoPregunta`, `TarjetaOpciones` | `ui/destino/componentes/PanelesVoz.kt` | `EncabezadoPregunta()` · `TarjetaOpciones(opciones: List<LugarDestino>, onElegir: (LugarDestino) -> Unit)` | Verificadas contra el código (bache 2): las firmas coinciden con las llamadas de `SeleccionDestinoScreen`. `TarjetaOpciones` muestra las coincidencias cuando hay varias (11.5, Destino). Detalle abajo. |

**Componentes de `ui/destino/componentes/` en detalle (verificado, bache 2)**

Reparto: `PanelesVoz.kt` (`BarraSuperior`, `EncabezadoPregunta`, `ZonaMicrofono`, `TarjetaTextoReconocido`, `TarjetaConfirmacion`, `TarjetaOpciones`), `ListaLugares.kt` (`FilaCategorias`, `ChipCategoria`, `CampoBusqueda`, `EncabezadoLista`, `FilaLugar`, `EstadoVacio`, `BotonVolver`) y `Comun.kt` (`Modifier.tarjeta`, `CategoriaLugar.icono()`, `BotonIcono`).

- **Visibilidad y estilo:** todo es público salvo `ChipCategoria` (privado) y lo de `Comun.kt` (`internal`). Ninguno de los tres archivos tiene `@Preview` (el de Destino está en la pantalla). Los textos son literales (sin `strings.xml`). Los colores salen de `CampusColors` (`TextoPrincipal`, `TextoSecundario`, `TextoSuave`, `Acento`, `Primario`, `Superficie`, `SuperficieAlta`, `Borde`), salvo dos colores fijos en el degradado del botón del micrófono (`#7B5CFF` y `#3B24C9`) y `Color.White`.
- **Dependencias que frenan moverlos a `ui/components/`:** `ListaLugares.kt` importa `OrdenLugares` de `ui.destino` y Coil (`AsyncImage`); `EncabezadoLista` no se puede mover sin llevarse `OrdenLugares` o abstraerlo. Los de `PanelesVoz.kt` que reciben `LugarDestino` dependen del dominio.

| Componente | Qué dibuja | Cuidados |
|---|---|---|
| `BarraSuperior` | Fila de al menos 64 dp: `BotonIcono` «Volver» (flecha), título fijo «Destino» (22 sp) y `BotonIcono` «Ajustes». | Título fijo: unificar con la de Ubicarme mediante un parámetro `titulo`. |
| `EncabezadoPregunta` | Círculo de 72 dp con ícono de ubicación, título «¿A dónde quieres ir?» (28 sp, marcado como encabezado para TalkBack) y subtítulo «Puedes decir el nombre del lugar o elegirlo de la lista.». Sin parámetros. | El texto escrito no es el hablado: la `PREGUNTA` del ViewModel añade «Di el nombre del lugar.». |
| `ZonaMicrofono` | Zona de 200 dp: botón de 144 dp (degradado, sombra, micrófono de 64 dp) y dos halos de 168 y 196 dp que pulsan (escala 1 → 1,08 en 900 ms) solo mientras escucha. Debajo, «Escuchando…» (con ícono) o «Toca para hablar», como `liveRegion` Polite. La descripción del botón es «Micrófono. Escuchando. Toca dos veces para detener.» o «Micrófono. Toca dos veces para decir el nombre del lugar.». | Solo el botón es táctil. La transición infinita se crea siempre, aunque no escuche. `onClick` es el mismo en ambos estados: ⚠ la descripción promete «detener», pero lo que ocurre al tocar mientras escucha lo decide `alPresionarMicrofono`; confirmarlo en el ViewModel. |
| `TarjetaTextoReconocido` | Tarjeta con ícono, «Texto reconocido:» (14 sp), «“texto”» (22 sp) y ✕ (`BotonIcono` «Descartar texto reconocido»). Los dos textos se fusionan para TalkBack. | La composable añade las comillas «“ ”»: pasar el texto **sin** comillas. No es `liveRegion`: no se anuncia sola. |
| `TarjetaConfirmacion` | Tarjeta con ícono de ubicación, «¿Quieres ir a {nombre}?» (22 sp) y «Di sí o no.». Botones Sí (relleno, `Primario`) y No (contorno) de al menos 64 dp, 22 sp. La pregunta es `liveRegion` Polite; los botones dicen «Sí, ir a {nombre}» y «No, elegir otro lugar». | Título fijo de lugares. Siempre dice «Di sí o no.», incluso con `sinMicrofono` (no recibe ese dato). ⚠ El anuncio de TalkBack se suma a la voz del ViewModel (ver abajo). |
| `TarjetaOpciones` | Tarjeta con «Encontré varios lugares. ¿Cuál quieres?» (`liveRegion` Polite) y un `OutlinedButton` de al menos 56 dp por opción (ícono de categoría + nombre, 18 sp). | No limita cuántas dibuja (el ViewModel entrega 2–3). El botón no incluye la categoría en su descripción: TalkBack lee solo el nombre. El texto difiere del hablado («Encontré N lugares: A, B o C. Di cuál quieres.»). |
| `FilaCategorias` | Fila con scroll horizontal (10 dp entre chips): un chip por cada `CategoriaLugar.DESTACADAS` (texto `etiquetaPlural` + ícono) y al final el chip «Más» con un `DropdownMenu` con `OTRAS`. | **El conmutador está aquí, no en el ViewModel:** tocar un chip destacado ya activo llama `onElegir(null)`. Los del menú «Más» **no** conmutan: se quitan con «Quitar filtro», que solo aparece si hay una de `OTRAS` activa. Con una de `OTRAS` activa, «Más» muestra su nombre e ícono y queda resaltado. No hay chip «Todos». ⚠ El chip «Más» tiene `contentDescription` fijo «Más categorías»: con una categoría activa, TalkBack no dice cuál. |
| `ChipCategoria` (privado) | Píldora de al menos 48 dp; activo = fondo `Primario` al 18 % y borde de 2 dp `Acento`, inactivo = borde de 1 dp `Borde`. Semántica `selected`, rol botón. | Opcionalmente lleva flecha (el chip «Más») y descripción propia. |
| `CampoBusqueda` | `OutlinedTextField` de una línea, al menos 60 dp, placeholder «Buscar un lugar…», lupa y, si hay texto, botón «Borrar búsqueda». La tecla del teclado es Buscar y solo quita el foco: la lista se filtra al escribir. | El valor viene del estado del ViewModel (sin estado local). Cada cambio, incluido borrar, llama `alCambiarBusqueda` y **corta la voz**. ⚠ Sin `label`: comprobar con TalkBack que anuncia el placeholder. |
| `EncabezadoLista` | Título («Lugares cercanos» si el orden es `CERCANIA`, si no «Lugares»; encabezado para TalkBack) y, a la derecha, un botón de al menos 48 dp con `orden.etiqueta` e ícono de intercambio; descripción «{etiqueta}. Toca para cambiar el orden.». | ⚠ Dice «Lugares cercanos» aunque ninguna `distanciaMetros` tenga valor (sin ubicación). |
| `FilaLugar` | Tarjeta (radio 18 dp) clicable: miniatura de 64 dp (`AsyncImage` de Coil con recorte, o el ícono de la categoría si `imagenUrl` es `null`), nombre (18 sp), categoría (`etiqueta` + ícono), distancia («N m», solo si no es `null`) y flecha. Descripción: «{nombre}, {categoría}, a {N} metros. Toca para elegir este destino.». | Coil sin `placeholder` ni `error`: si la URL falla, se ve el cuadro vacío en vez del ícono. La distancia es siempre en metros («1200 m»), sin pasar a km. El nombre no tiene `maxLines`. |
| `EstadoVacio` | Mensaje opcional centrado (18 sp) y una acción de texto debajo (al menos 48 dp): «Limpiar filtros», «Reintentar». | Genérico. Firma invertida respecto a `MensajeVacio` (aquí `mensaje` es opcional y `accion` obligatoria; allí al revés): decidir al unificar. |
| `BotonVolver` | `OutlinedButton` de ancho completo, al menos 64 dp, forma de 18 dp, borde de 2 dp, flecha + «Volver» (20 sp). | Incluye su propio padding (20 dp horizontal, 12 dp vertical). |

Íconos de `CategoriaLugar.icono()` (todos `outlined`): `BIBLIOTECA` → `MenuBook` (versión `AutoMirrored`), `CAFETERIA` → `LocalCafe`, `BANO` → `Wc`, `BLOQUE` → `Apartment`, `AUDITORIO` → `TheaterComedy`, `DEPORTES` → `SportsSoccer`, `ADMINISTRACION` → `AccountBalance`, `ENTRADA` → `MeetingRoom`.

⚠ **Varias voces a la vez (comprobar en un dispositivo con TalkBack):** además de la voz del `VoiceController`, hay **tres** `liveRegion` Polite: el estado de `ZonaMicrofono`, la pregunta de `TarjetaConfirmacion` y el título de `TarjetaOpciones`. Pueden hablar a la vez que el ViewModel, y TalkBack podría estar hablando justo cuando arranca `listen`, de modo que el reconocedor capte esa voz. El código por sí solo no permite saberlo.

**`AlertaFormSheet` en detalle (verificado)**

- **Sin estado propio** sobre la alerta: recibe el borrador `alerta` y avisa cada cambio con `onCambio(alerta.copy(...))`. Quien la use guarda el borrador, valida y persiste. Lo único que guarda por dentro es si está abierto el diálogo "¿Eliminar esta alerta?".
- **Campos:** `mensaje` (máx. `MAX_MENSAJE` caracteres, con contador; si `error != null` lo muestra en lugar de la ayuda), `tipo` (chips: Agua, Mobiliario, Escalones, Obra, Vehículos, Otro), `prioridad` (Normal / Alta), `radio` (deslizador de 5 a 100 m en saltos de 5), `activa` (interruptor) y la posición `lat, lng` **solo de lectura**.
- **Botones** (56 dp mínimo): Cancelar, Eliminar (**solo si `!esNueva`**, con confirmación) y Guardar. Cerrar la hoja (deslizar o tocar fuera) equivale a `onCancelar`.
- **No valida nada**: si el mensaje está vacío, o falta la posición, lo decide el ViewModel y lo devuelve por `error`.
- **"Cada cambio se refleja en vivo en el mapa"**: lo hace quien recibe `onCambio`. En `EditorMapaViewModel` el borrador vive **aparte** de la lista (`formulario` frente a `alertas`), así que cancelar **no necesita revertir** nada.
- **Para reutilizarlo desde la recolección** basta importarlo (es público) y pasarle una `Alerta` con la posición actual. Depende de `Alerta` y de `MAX_MENSAJE` (`const val MAX_MENSAJE = 200`, público, declarado al inicio de `EditorMapaViewModel.kt`, mismo paquete `ui.admin.mapa`). Por la regla 4, si lo usan dos vistas debería moverse a `ui/components/` junto con esa constante.
- La lista de tipos (`private val TIPOS`) está **duplicada**: aquí, en el mapa web y en la tabla de `Alerta`. Verificado: en la web son `TIPOS` y `TIPO_NOMBRE` en `editor_mapa.js` **y** las opciones del `<select id="f-tipo">` de `editor_mapa.html`; añadir un tipo exige cambiar cuatro sitios (esta lista, esos dos y la tabla de `Alerta`).
- Accesibilidad: el `Slider` no lleva descripción propia (el texto "Radio de activación: N m" va aparte), así que TalkBack lo anuncia por su valor; conviene un `stateDescription` del tipo "N metros".

**`EditorMapaViewModel` y el formulario de alerta (verificado, `ui/admin/mapa/EditorMapaViewModel.kt`)**

| Pieza | Detalle |
|---|---|
| `EditorMapaViewModel()` | `ViewModel` sin parámetros. Estado en `ui: StateFlow<EditorMapaUi>`. Todo vive **en memoria**, con datos de ejemplo (`demo1`, `demo2` y el lugar "Biblioteca") que hay que borrar al conectar el repositorio. |
| `EditorMapaUi` | `alertas`, `lugares`, `pendientes: Set<String>` (ids con cambios sin sincronizar), `formulario: Alerta?` (borrador; `null` = cerrado), `formularioEsNuevo`, `error`, `sincronizando`. Calculados para el mapa web: `alertasJson`, `lugaresJson` y `borradorJson` (claves `id`, `lat`, `lng`, `mensaje`, `tipo`, `prioridad`, `radio`, `activa`). |
| `abrirFormulario(id: String?, lat, lng)` | Con un `id` existente abre esa alerta para editar; si no, crea una nueva (`UUID`, mensaje vacío) en esa posición. |
| `actualizarFormulario(a)` | Reemplaza el borrador y limpia el error (es el `onCambio` de `AlertaFormSheet`). |
| `cancelarFormulario()` | Cierra el formulario sin tocar `alertas`. |
| `guardarFormulario()` | Valida el mensaje **ya recortado**: vacío → "Escribe el mensaje que se leerá al usuario."; más de `MAX_MENSAJE` → "Máximo 200 caracteres.". No valida `radio`, `tipo`, `prioridad` ni posición. Si es válido, reemplaza o agrega la alerta, la marca como pendiente y cierra. |
| `mover(id, lat, lng)` · `eliminar(id)` | Se aplican al instante y marcan el id como pendiente; `eliminar` además cierra el formulario si estaba editando esa alerta. |
| `sincronizar()` | Si hay pendientes y no está sincronizando: espera 600 ms (simulado) y **vacía `pendientes`**. TODO: enviar al backend y, si falla, dejarlos intactos. |

Cuidados:
- **Se pierde todo al salir de `admin/mapa`:** el ViewModel pertenece a la entrada de navegación y las alertas están solo en memoria. Hasta que exista el repositorio, nada de lo que cree el admin sobrevive.
- **`pendientes` guarda solo ids, no la operación** (crear, modificar o eliminar). Una alerta creada y eliminada antes de sincronizar deja un id pendiente que el servidor nunca conoció. Antes de conectar la API hay que guardar el tipo de cambio.
- `Alerta.toJson()` es `private`: otra vista que hable con el mapa web tendría que copiarla. Candidata a quedar junto al modelo.
- La validación vive dentro del ViewModel: para reutilizarla desde la recolección conviene extraerla como función pura (11.7).

**`EditorMapaScreen` y `EditorBridge` (verificado, `ui/admin/mapa/EditorMapaScreen.kt`, `assets/editor_mapa.html` y `assets/editor_mapa.js`)**

| Pieza | Detalle |
|---|---|
| `EditorMapaScreen` | `(onVolver, onVerLista, posicionAdmin: () -> Pair<Double, Double>?, modifier = Modifier.fillMaxSize(), vm: EditorMapaViewModel = viewModel())`. Conecta el ViewModel con el mapa y, cuando `ui.formulario != null`, muestra `AlertaFormSheet` encima. Es la que registra el `NavHost` (`admin/mapa`). |
| `EditorMapaContent` | `(alertasJson: String, lugaresJson: String, pendientes: Int, borradorJson: String?, eventos: EditorMapaEventos, modifier, miPosicion: Pair<Double, Double>? = null)`. Solo dibuja el `WebView` de `assets/editor_mapa.html` (Leaflet + OpenStreetMap en línea). No conoce el ViewModel. |
| `EditorMapaEventos` | `interface` pública con 8 funciones: `abrirFormulario(id: String?, lat, lng)`, `cancelarFormulario()`, `moverAlerta(id, lat, lng)`, `eliminarAlerta(id)`, `sincronizar()`, `verLista()`, `pedirMiPosicion()` y `salir()`. |

**Puente `EditorBridge`, web → app** (métodos `@JavascriptInterface`; todos se pasan al hilo principal con `Handler(Looper.getMainLooper())`, porque llegan en un hilo del `WebView`):

| Función | Argumentos / qué hace |
|---|---|
| `listo()` | La página terminó de cargar. Hasta entonces la app no le envía nada. |
| `abrirFormulario(json)` | `{"id": texto o null, "lat", "lng"}`. `id = null` crea una alerta nueva en esa posición. |
| `moverAlerta(id, lat, lng)` · `eliminarAlerta(id)` | Se aplican al instante en el ViewModel. |
| `cancelarFormulario()` · `sincronizar()` · `verLista()` · `pedirMiPosicion()` · `salir()` | Sin argumentos. |

**Puente, app → web** (`evaluateJavascript`; el estado se reenvía completo cada vez que cambia y solo después de `listo()`):

| Función JS | Qué recibe |
|---|---|
| `setInsets(topDp, bottomDp)` | Alto de las barras del sistema **en dp**: `env(safe-area-inset-*)` no funciona en `WebView`, por eso se lo pasa la app. |
| `cargarAlertas(json)` · `cargarLugares(json)` | Un **texto** JSON entre comillas (se arma con `JSONObject.quote`), no un objeto: el JS hace `JSON.parse` (verificado). |
| `setPendientes(n)` | Número de alertas sin sincronizar. |
| `setBorrador(json)` (o `null`) | Vista en vivo del borrador del formulario; `null` = formulario cerrado. |
| `setMiPosicion(lat, lng)` | Solo se llama si `miPosicion != null`. Dibuja el punto y **centra** el mapa con zoom de 18 o más cada vez que se llama. |
| `upsertAlerta(json)` · `quitarAlerta(id)` | Existen en el JS, pero **Kotlin no las llama**: hoy todo entra por `cargarAlertas`, que reemplaza la lista completa y deselecciona si la alerta elegida ya no está. |
| `window.onAtras()` | Lo invoca el botón Atrás del sistema (`BackHandler`). El JS sale de los modos temporales (mover, colocar, formulario) y, al final, llama a `salir()`. |

Cuidados:
- **`posicionAdmin` hoy es `{ null }`** (11.8): el botón de "mi posición" no hace nada y no avisa. La posición se guarda con `remember` (no sobrevive a rotar la pantalla). ⚠ Deducido del código, no probado: como se envía con `LaunchedEffect(listo, miPosicion)`, volver a pedirla con **las mismas coordenadas** no vuelve a centrar el mapa.
- **Sin internet:** `editor_mapa.html` carga Leaflet desde `unpkg.com`. Si falla, `MapaBase.iniciar` (11.9) muestra «No se pudo cargar el mapa. Revisa tu conexión a internet.» y **ya dejó definidos** `window.onAtras` (llama a `salir()`), `setInsets` y el botón Volver; `editor_mapa.js` termina antes de llamar a `listo()`. Resultado: Atrás y Volver funcionan, pero la app nunca envía alertas ni lugares. (Antes el JS terminaba antes de definirlos y ambos botones quedaban muertos.) Probado con jsdom, no en dispositivo.
- **Orden de `window.onAtras()`** (siempre devuelve `true`, y Kotlin ignora el valor): sale de mover → sale de colocar → cancela el borrador (`cancelarFormulario`) → deselecciona → si hay pendientes pide confirmar "Tienes cambios sin sincronizar. ¿Salir de todas formas?" → `salir()`.
- **`sincronizando` y `error` del ViewModel no llegan al mapa:** `EditorMapaContent` solo recibe `pendientes`; `error` solo se ve en la hoja del formulario. Cuando `sincronizar()` llame a la API real habrá que ampliar el puente para mostrar progreso o fallo.
- **Registro fuera de `AppLog`:** usa `android.util.Log` con el tag `EditorMapa` (mensajes de la consola JS y errores de carga de recursos), así que **no queda en `files/logs/app.log`**. Un recurso que falla (por ejemplo, teselas sin internet) solo deja un `Log.e`: no hay aviso en pantalla.
- `WebView.setWebContentsDebuggingEnabled(true)` solo en builds depurables (`chrome://inspect`).
- **Seguridad del puente (verificado):** `addJavascriptInterface` expone `EditorBridge` a todo el JavaScript de la página, y `editor_mapa.html` carga Leaflet 1.9.4 desde `unpkg.com` **sin `integrity`**; además `bindTooltip(l.nombre)` de los lugares hace que Leaflet interprete el texto como HTML. Los demás datos se insertan con `textContent` (patrón a mantener). Con datos locales el riesgo es bajo; reevaluarlo al conectar `/admin/alerts` o servir Leaflet desde `assets/` (decisión 13).
- **Todo en línea:** Leaflet y la fuente Inter (Google Fonts) vienen de internet, y las teselas del servidor público de OpenStreetMap (sujetas a su política de uso). El `viewport` lleva `user-scalable=no`.
- **Prueba sin teléfono:** abrir `editor_mapa.html` en un navegador de escritorio activa un modo demo (3 alertas, el lugar "Biblioteca" y `window.prompt` en lugar del formulario nativo): sirve para iterar la interfaz sin compilar la app.
- **Las dos "Ver lista"** (arriba y en el dock) llaman a `verLista()`; como `onVerLista` está vacío en `AppNav`, **no pasa nada** y no hay aviso (el toast solo sale en el navegador).
- **Eliminar tiene dos confirmaciones distintas:** desde la tarjeta del mapa, un modal web ("¿Eliminar esta alerta? Dejará de avisarse a los usuarios."); desde `AlertaFormSheet`, el diálogo de Compose (11.5).
- **Solo del lado web:** los filtros por tipo, prioridad y estado (nunca ocultan la alerta seleccionada) y las capas `cobertura` y `rutas`, que existen como grupos **vacíos** (sin datos, sección 10). Las claves de `tipo` y `prioridad` que el JS no reconoce no fallan: `tipo` sale con ⚠️ y el nombre "Alerta", y `prioridad` se pinta como "Normal" en ámbar (`#f59e0b`; alta es `#ef4444`).
- `onRelease` destruye el `WebView`: no guardar referencias a él fuera de la composición.

**`PanelAdminViewModel` (verificado, `ui/admin/panel/PanelAdminViewModel.kt`)**

| Pieza | Detalle |
|---|---|
| Constructor | `PanelAdminViewModel(repo: AdminRepository, session: SessionManager)`. `Factory(context)` crea `AdminRepositoryStub()` y `SessionManager(context.applicationContext)` (uno por ViewModel, como pide 11.3). |
| `state: StateFlow<PanelUiState>` | `nombre` (primer nombre: lo que hay antes del primer espacio del nombre de la sesión), `rolTexto` (fijo: "Administrador del sistema"), `resumen: ResumenAdmin?`, `cargandoResumen` (empieza en `true`), `errorResumen`. |
| `eventos` | `Channel(Channel.BUFFERED)` + `receiveAsFlow()`: cada evento lo recibe **un** recolector y queda guardado si llega antes de que alguien recoja. `PanelEvento.SesionCerrada` (volver al flujo público) y `PanelEvento.SinSesion` (ir a Login). |
| `cargarResumen()` | Pone `cargandoResumen = true` y `errorResumen = false`, llama a `repo.obtenerResumen()` y, ante **cualquier** `Exception`, deja `errorResumen = true`. Sirve también de reintento. |
| `cerrarSesion()` | `session.cerrarSesion()` y emite `SesionCerrada`. |

Cuidados:
- **La guarda de rol corre solo en `init`:** sin sesión o con rol distinto de `ADMIN` emite `SinSesion` y no carga nada; mientras el ViewModel viva no se vuelve a comprobar (11.8: `AppNav` tampoco protege las demás rutas `admin/*`).
- `session.obtener()` se llama en el hilo principal y sin `try/catch`. ⚠ Deducido de unir esto con 11.3 (el primer acceso al almacén cifrado puede tardar y lanzar excepción si falla el Keystore): ese fallo cerraría la app al abrir el panel.
- Si `cargarResumen()` falla después de haber cargado antes, `resumen` **conserva el dato anterior** junto con `errorResumen = true`: `PanelAdminScreen` muestra entonces el aviso de error **y** los datos viejos, con el chip "En tiempo real" (ver abajo).
- Llamarla dos veces seguidas lanza dos cargas sin cancelar la primera; gana la que termine última.
- `catch (e: Exception)` también traga `CancellationException`; no copiarlo en código que deba cancelarse (Detalle de video sí la relanza). No registra nada en `AppLog`.
- Con el stub (`nombre = "Administrador"`) el saludo sale "Administrador", no un nombre propio.

**`GaleriaViewModel` (verificado, `ui/admin/imagenes/GaleriaViewModel.kt`)**

| Pieza | Detalle |
|---|---|
| Constructor | `GaleriaViewModel(repositorio: VideoRepository)`. `Factory(appContext)` crea `AssetsVideoRepository(appContext)`. Estado en `uiState: StateFlow<GaleriaUiState>`. Carga en `init`. |
| `GaleriaUiState` | `cargando` (empieza en `true`), `error: String?`, `videos`, `todas: List<Foto>` (las fotos de todos los videos), `filtros`, `modo`, `pagina` (desde 1) y `seleccion: Set<String>` con el **`uid`** de cada foto (11.6). Calculadas: `filtradas`, `totalPaginas` (mínimo 1), `paginaActual` y `lugares` (lugares distintos, ordenados). |
| `GaleriaFiltros` | `busqueda`, `lugar`, `videoId`, `estado`, `calidad`; todos opcionales y combinados con **Y**. `hayActivos` dice si hay alguno. |
| `ModoVista` · `FOTOS_POR_PAGINA` | `CUADRICULA` / `MAPA` (`cambiarModo`). `const val FOTOS_POR_PAGINA = 24`, público, en este archivo. |
| Acciones | `cargar()`, `buscar`, `filtrarLugar`, `filtrarVideo`, `filtrarEstado`, `filtrarCalidad`, `limpiarFiltros`, `irAPagina(n)` (se acota a 1…`totalPaginas`), `alternarSeleccion(uid)`, `limpiarSeleccion`, `eliminarSeleccion`, `reasignarSeleccion(lugar)`. |

Cuidados:
- **Eliminar y reasignar no pasan por `VideoRepository` ni por `EdicionesLocales`:** solo cambian `todas` en el estado (y `videos` queda sin tocar). Al salir de la pantalla se pierden, y una foto "eliminada" aquí **sigue apareciendo** en Lista y Detalle de video. `cargar()` (el reintento) también restaura lo eliminado en memoria.
- **No escucha `cambios()`:** carga una sola vez, así que lo que se borre o renombre en Detalle de video solo se ve al volver a entrar en Galería (el `VideoDetalleViewModel` sí lo hace, ver abajo).
- Cambiar cualquier filtro vuelve a la página 1 y **vacía la selección**; cambiar de página **no** la vacía, y `eliminarSeleccion` / `reasignarSeleccion` actúan sobre toda la selección, incluidas fotos de otras páginas que no se ven. La interfaz debe mostrar el total seleccionado, no solo el de la página.
- La búsqueda ignora mayúsculas pero **no tildes**, y mira nombre de archivo, nombre del video y lugar. Según 11.7, `BuscarLugares.filtrar` sí ignora tildes: no son equivalentes.
- `filtradas`, `totalPaginas`, `paginaActual` y `lugares` son *getters* **sin caché**: `filtradas` se recalcula en cada lectura, y `GaleriaContent` lee `filtradas`, `paginaActual` y `totalPaginas` en cada recomposición (el filtro corre **tres veces**). Aceptable con pocos cientos de fotos; con el backend, filtrar y paginar en el servidor.
- `reasignarSeleccion` guarda `lugar.trim()`: con texto en blanco asigna `""` (no `null`) y esa cadena vacía aparece como un lugar más en `lugares`. `GaleriaScreen` ya deshabilita "Reasignar" con el texto en blanco, pero el ViewModel no valida: otra vista que lo llame debe hacerlo.
- Si se eliminan todas las fotos del lugar que está filtrado, el filtro sigue activo pero ese lugar ya no está en `lugares`: lista vacía sin opción visible para quitarlo (`eliminarSeleccion` no limpia filtros) salvo `limpiarFiltros()`.
- `cargar()` captura toda `Exception` con un mensaje fijo ("No se pudieron cargar las imágenes") y no registra nada en `AppLog`.

**`VideoDetalleViewModel` (verificado, `ui/admin/videos/VideoDetalleViewModel.kt`; la pantalla y el puente, más abajo)**

| Pieza | Detalle |
|---|---|
| Constructor | `VideoDetalleViewModel(videoId: String, repositorio: VideoRepository)`. `Factory(appContext, videoId)` crea `AssetsVideoRepository(appContext)`. Estado en `ui: StateFlow<VideoDetalleUiState>`. |
| `VideoDetalleUiState` | `cargando` (empieza en `true`), `noEncontrado`, `videoJson: String?` y `otrosJson` (`"[]"` por defecto). Ya vienen **serializados**: el mapa web recibe JSON. |
| `videoJson` | `{id, nombre, fecha, fotos: [{id, url, thumb, lat, lng, rumbo}]}`. `fecha` = los 10 primeros caracteres de `creadoEn` (espera `"2026-10-09…"`); `rumbo` es número o `null`. **No** incluye `lugar`, `estado`, `calidad` ni `capturadaEn`. |
| `otrosJson` | `[{id, nombre, fotos: [{lat, lng}]}]` con **los demás videos**, para comparar cobertura en el mapa. |
| Acciones | `renombrar(nombre)` (recorta espacios), `eliminarFoto(fotoId)`, `eliminarVideo()`. Lanzan la operación en `viewModelScope` y no esperan resultado. |

Cuidados:
- **Patrón de recarga (copiarlo):** en `init` solo se recoge `repositorio.cambios()`; su primera emisión **es** la carga inicial, así que no hay otra llamada a `cargar()` y se evita la doble carga que advierte 11.6. Cada renombrar o eliminar vuelve a leer **todos** los manifests, porque se filtra por `id` sobre `obtenerVideos()`.
- **`huboVideo`:** una vez visto el video, si desaparece (lo eliminó la propia pantalla) **no** pasa a `noEncontrado` y `videoJson` conserva el último valor. `VideoDetalleScreen` no navega tras `eliminarVideo()`: lo hace el JS, que llama a `salir()` 900 ms después (ver `VideoBridge`, abajo).
- **Errores:** una `Exception` en `cargar()` antes de haber visto el video se muestra como `noEncontrado` (no distingue "no existe" de "falló la lectura"); después se ignora en silencio. Hoy casi no ocurre (un manifest roto se omite), pero con un repositorio remoto un corte de red se vería como "no encontrado": hará falta un estado de error. Sí relanza `CancellationException`.
- **`renombrar`, `eliminarFoto` y `eliminarVideo` no tienen `try/catch`:** si el repositorio lanza una excepción (el futuro `RemoteVideoRepository` con `IOException`), **la app se cierra**. Tampoco hay estado de progreso ni de error: es el pendiente "progreso y reintento del borrado" de la sección 10. `renombrar` no valida nada: la validación vive en el JS (ver `VideoBridge` más abajo).
- `fecha` solo funciona si `creadoEn` viene en ISO-8601 (11.6: hoy es texto sin convertir).

**`PanelAdminScreen` (verificado, `ui/admin/panel/PanelAdminScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `PanelAdminScreen` | `(onRecolector, onLugares, onMapaAlertas, onImagenes, onVideos, onEstadisticas, onAjustes, onVolverModoPublico, onSesionCerrada, onSinSesion, viewModel = viewModel(factory = PanelAdminViewModel.Factory(LocalContext.current.applicationContext)))`. Recoge `viewModel.eventos` en un `LaunchedEffect(Unit)`: `SesionCerrada` → `onSesionCerrada()`, `SinSesion` → `onSinSesion()`. El `Channel` con búfer es lo que permite que un `SinSesion` emitido en `init` llegue aunque aún no haya colector. |
| `PanelAdminContent` | `internal` · `(state: PanelUiState, acciones: PanelAcciones)`. Sin lógica; 3 `@Preview` privados (normal, cargando, error). |
| `PanelAcciones` | `data class` con 10 lambdas (`{}` por defecto): `onRecolector`, `onLugares`, `onMapaAlertas`, `onImagenes`, `onVideos`, `onEstadisticas`, `onAjustes`, `onCerrarSesion`, `onVolverModoPublico`, `onReintentarResumen`. |
| Piezas privadas | `Encabezado`, `FilaTarjetas` / `TarjetaAcceso` (con `Acceso`), `ResumenRapido`, `TileDato`, `ChipTiempoReal`, `Pie`. No se reutilizan sin extraerlas. |

Cuidados:
- **No lee `cargandoResumen`:** mientras carga no hay indicador; los 5 datos muestran "—", igual que con error.
- Con `errorResumen` aparece "No se pudo cargar el resumen." con un botón "Reintentar" (48 dp), pero si ya había un `resumen` anterior se sigue dibujando.
- **`ChipTiempoReal` ("En tiempo real")** se muestra siempre que `resumen != null`, aunque `errorResumen` sea `true`. El ViewModel carga **una sola vez**, sin sondeo: el texto promete más de lo que hace.
- **"Cerrar sesión" actúa al primer toque, sin confirmación**, y se pinta con `CampusColors.Peligro` (morado, no rojo; 11.4).
- `ResumenAdmin` (verificado contra `ResumenAdmin.kt`, bache 3; ver 11.6): `totalFotos`, `totalLugares`, `alertasActivas`, `ultimoVideoNumero`, `ultimoVideoFecha` (milisegundos) y `fotosPendientes`, en ese orden de constructor. `numero()` usa `NumberFormat.getIntegerInstance()` (separador de miles según la región) y "—" si es nulo; `textoFecha` da "Hoy, HH:mm", "Ayer, HH:mm" o "d MMM, HH:mm".
- Los 5 datos van en **una sola fila** (`weight(1f)` cada uno) con etiquetas de 11 sp: en ~390 dp ya quedan muy angostos. ⚠ No se probó con la fuente grande del sistema.
- `LaunchedEffect(Unit)` captura `onSesionCerrada` y `onSinSesion` de la primera composición (sin `rememberUpdatedState`): no pasar lambdas que dependan de estado que cambie.
- Columna raíz con `systemBarsPadding()` + `verticalScroll`. "Versión X" sale de `packageManager.getPackageInfo(...)` dentro de `runCatching` ("—" si falla); "Panel de administración · Campus Navi" está fijo.
- Accesibilidad: cada tarjeta y cada dato se anuncian combinados (`mergeDescendants`); los títulos llevan `heading()`; Ajustes mide 56 dp.
- `onRecolector`, `onLugares`, `onEstadisticas` y `onAjustes` llevan hoy a rutas placeholder (11.8).

**`GaleriaScreen` y `GaleriaColores` (verificado, `ui/admin/imagenes/GaleriaScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `GaleriaScreen` | `(onVolver, onAbrirImagen: (videoId, fotoId) -> Unit, viewModel = viewModel(factory = GaleriaViewModel.Factory(LocalContext.current.applicationContext)))`. Con selección activa, el botón Atrás **primero limpia la selección** (`BackHandler(enabled = seleccion.isNotEmpty())`). |
| `GaleriaContent` | `(state: GaleriaUiState, acciones: GaleriaAcciones, modifier)`. Público, sin ViewModel, con 2 `@Preview` privados. Cabecera, búsqueda, 4 filtros, selector de modo, cuadrícula de 2 columnas, barra de selección y paginador. |
| `GaleriaAcciones` | `data class` con 14 lambdas (`{}` por defecto): `onVolver`, `onReintentar`, `onBuscar`, `onLugar`, `onVideo`, `onEstado`, `onCalidad`, `onLimpiarFiltros`, `onModo`, `onPagina`, `onAbrirFoto(Foto)`, `onAlternarSeleccion(uid)`, `onEliminar`, `onReasignar(lugar)`. |
| `GaleriaColores` | `internal object` con la paleta de la maqueta; también la usa `VideosScreen`. Equivalencias en 11.4. |

**Piezas privadas de la Galería, candidatas a `ui/components/`** (regla 4: hoy no se pueden importar):

| Pieza | Firma | Qué hace / duplicación |
|---|---|---|
| `CampoTexto` | `(valor, onCambio, placeholder, descripcion, modifier, icono?, trailing?)` | `BasicTextField` de una línea, 56 dp, con ícono y acción final opcionales y `contentDescription` propio. |
| `FiltroChip<T>` | `(etiqueta, seleccionado: T?, opciones: List<T>, textoDe, onSeleccionar: (T?) -> Unit, textoTodos = "Todos")` | Chip de 48 dp con menú y opción "Todos". Genérico: sirve para los filtros pendientes de 7.13. |
| `SelectorModo` | `(modo: ModoVista, onModo)` | Dos segmentos Cuadrícula / Mapa. Atado a `ModoVista`. |
| `Paginador` + `paginasVisibles(actual, total)` | `(actual, total, onPagina)` | Anterior / siguiente y números con "…" (ej. 1 2 3 … 8); solo se dibuja si `total > 1`. `paginasVisibles` es lógica pura: se podría probar sin emulador si se hace `internal`. |
| `BarraSeleccion` + `BotonLote` | `(cantidad, onReasignar, onEliminar)` | "N seleccionadas" y los botones Reasignar / Eliminar. |
| `MensajeVacio` | `(texto, accion?, onAccion)` | **Duplicada** con `Mensaje` (VideosScreen) y con `EstadoVacio` de `ui/destino/componentes/ListaLugares.kt` (arriba; firma invertida: allí `mensaje` es opcional y `accion` obligatoria): unificar. |
| `BarraSuperior` | `(onVolver)` | Volver + título fijo "Galería de imágenes". Otra copia de la barra superior (ver `BarraSuperior` arriba); `VideosScreen` arma la suya en línea. |

Cuidados:
- La **`BarraSeleccion` se dibuja siempre** (en `bottomBar`), también con 0 seleccionadas ("0 seleccionadas", botones deshabilitados); `enModoSeleccion` solo decide qué hace el toque sobre una foto.
- **Selección:** pulsación larga sobre la tarjeta (acción "Seleccionar" para TalkBack); ya en modo selección, el toque alterna. El círculo de la esquina (48 dp de área táctil) está **oculto a la accesibilidad** (`clearAndSetSemantics`).
- **El diálogo de eliminar dice** "del dataset y del sistema de ubicación. Esto no se puede deshacer", pero hoy solo quita las fotos **de la memoria de esta pantalla** (ver `GaleriaViewModel`): el texto promete más de lo que hace.
- **Reasignar:** campo de texto libre con el botón deshabilitado si está en blanco (TODO: selector de lugares reales, 7.6). Cualquier texto crea un "lugar" nuevo.
- El modo `MAPA` solo muestra un mensaje provisional.
- Miniaturas con Coil (`AsyncImage(model = foto.urlMiniatura)`, `contentDescription = null`: la tarjeta ya se anuncia completa con nombre, video, lugar, estado, "alta calidad" y "seleccionada"). Si la URL falla solo queda el fondo `Placeholder`.
- `NumberFormat.getIntegerInstance()` para "N imágenes" (según la región).

**`VideosScreen` y `VideosViewModel` (verificado, `ui/admin/videos/VideosScreen.kt` y `VideosViewModel.kt`)**

| Pieza | Detalle |
|---|---|
| `VideosScreen` | `(onVolver, onAbrirVideo: (videoId) -> Unit, viewModel = viewModel(factory = VideosViewModel.Factory(LocalContext.current.applicationContext)))`. Recoge `viewModel.uiState` con `collectAsState()`. El estado es `VideosUiState(cargando = true, error: String? = null, videos = emptyList())` y el ViewModel tiene `reintentar()` (detalle abajo). |
| `VideosContent` | `(state: VideosUiState, onVolver, onAbrirVideo, onReintentar, modifier)`. Público, **sin `@Preview`**. Muestra cargando, error con "Reintentar", vacío ("Todavía no hay videos.") o la lista con "N videos". |
| Tarjeta de video | Nombre, y una línea con la fecha `dd/MM/yyyy` (los 10 primeros caracteres de `creadoEn`, invertidos), "N fotos" y la distancia (`Video.distanciaMetros`: "N m" o "X,XX km" según la región). Más un estado calculado: **Sin fotos**, **Con errores** (alguna `ERROR`), **Procesado** (todas `PROCESADA`) o **Pendiente de proceso**. El estado va en texto además del color. |

Cuidados:
- El orden es el del repositorio (por carpeta, 11.6); aún no hay orden ni búsqueda (sección 10).
- Usa `GaleriaColores` del paquete `ui.admin.imagenes`: dependencia cruzada hasta que se muevan a `CampusColors`.
- La fecha supone formato ISO (`2026-10-09…`); con otro formato sale mal.
- **`VideosViewModel` sí recoge `repositorio.cambios()`** (verificado): el ViewModel de la lista sigue vivo en la pila mientras se ve el detalle, y al volver tras renombrar o eliminar un video la lista se recarga sola.
- Accesibilidad: tarjeta con rol de botón y descripción completa ("Video X, fecha, N fotos, distancia, estado"); mínimo 72 dp de alto.

**`VideosViewModel` en detalle (verificado)**

- `VideosViewModel(repositorio: VideoRepository)`; su `Factory(appContext)` crea `AssetsVideoRepository(appContext)` (**espera el contexto de la aplicación**). Expone `uiState` y no tiene flujo de eventos. No usa `AppLog`.
- En el `init` recoge `repositorio.cambios()` y llama a `cargar()` por cada emisión: la primera emisión **es** la carga inicial (no hay otra) y las siguientes llegan cuando el detalle renombra o elimina. Cada una relee **todos** los manifests (11.6).
- `cargar()`: con éxito pone `cargando = false`, `error = null` y `videos`. Con cualquier `Exception` (salvo `CancellationException`, que relanza) pone `cargando = false` y `error = "No se pudieron cargar los videos"` (texto fijo, sin registrar) y **conserva** la lista anterior en `videos`.
- `reintentar()` vuelve a llamar a `cargar()` **sin** poner `cargando = true`: durante el reintento no hay indicador de carga y el error sigue en el estado hasta que termine. Como `cargar()` corre dentro del `collect`, las recargas por `cambios()` son secuenciales, pero un `reintentar()` simultáneo puede solaparse con una (gana la última en terminar).

**`VideoDetalleScreen` y `VideoBridge` (verificado, `ui/admin/videos/VideoDetalleScreen.kt`, `assets/video_detalle.html` y `assets/video_detalle.js`)**

| Pieza | Detalle |
|---|---|
| `VideoDetalleScreen` | `(videoId: String, onVolver, onAbrirImagen: (videoId, fotoId) -> Unit, modifier, vm = viewModel(key = "video-$videoId", factory = VideoDetalleViewModel.Factory(LocalContext.current.applicationContext, videoId)))`. La `key` da un ViewModel distinto por video. Dibuja `VideoDetalleContent` y, encima, `NoEncontrado` si `ui.noEncontrado`. |
| `VideoDetalleContent` | `(videoJson: String?, otrosJson: String, eventos: VideoDetalleEventos, modifier)`. Público, **sin `@Preview`**. Solo el `WebView` de `assets/video_detalle.html` (Leaflet + OpenStreetMap en línea). |
| `VideoDetalleEventos` | `interface` con 5 funciones: `abrirFoto(fotoId)`, `renombrar(nombre)`, `eliminarFoto(fotoId)`, `eliminarVideo()` y `salir()`. |
| `NoEncontrado` | Privado: "No se encontró este video." y un botón "Volver"; fondo fijo `#0A0E1A`. |

**Puente `VideoBridge`, web → app** (`@JavascriptInterface`; todo pasa al hilo principal): `listo()`, `abrirFoto(id)`, `renombrar(nombre)`, `eliminarFoto(id)`, `eliminarVideo()`, `salir()`. **App → web:** `setInsets(topDp, bottomDp)`, `cargarOtros(json)`, `cargarVideo(json)` (solo si `videoJson != null`; ambos como texto JSON entre comillas; el JS hace `JSON.parse`) y `window.onAtras()` (el JS cierra primero el diálogo o la foto seleccionada y al final llama a `salir()`).

Cuidados:
- **Kotlin no navega tras `eliminarVideo()`; lo hace el JS** (verificado): llama a `eliminarVideo`, muestra "Video eliminado" y **900 ms después** llama a `salir()` sin esperar resultado. Si el borrado fallara (futuro `RemoteVideoRepository`, ver el `try/catch` que falta en 11.5), el admin ya habría salido.
- **No usa `ui.cargando`:** mientras llega el JSON se ve el mapa vacío, sin indicador.
- **Sin internet:** si Leaflet (`unpkg.com`) no carga, `MapaBase.iniciar` (11.9) avisa en pantalla y **ya dejó definidos** `window.onAtras` (llama a `salir()`), `setInsets` y el botón Volver; `video_detalle.js` termina antes de llamar a `listo()`, así que Atrás y Volver funcionan pero la app no envía el video. Probado con jsdom, no en dispositivo. El registro va por `Log` con el tag `VideoDetalle`, no por `AppLog`.
- **Orden de `window.onAtras()`:** cierra el diálogo abierto → deselecciona la foto → `salir()` (aquí no hay confirmación de pendientes).
- **Confirmaciones (en el JS):** eliminar el video exige **escribir su nombre** (la sección 10 anota como pendiente una "confirmación por pulsación larga"; hoy es esta). Eliminar una foto es **optimista**: la quita de la lista al instante y, si era la última, ofrece eliminar también el video. El `WebView` no muestra `window.prompt`, por eso hay un diálogo propio (`dialogo()`, `role="alertdialog"`).
- **Renombrar se valida en el JS, no en el ViewModel:** texto no vacío, distinto del actual y de máximo 40 caracteres; **no** se comprueba que el nombre no exista ya en otro video.
- **Formatos duplicados con Kotlin:** el JS calcula su propia distancia (haversine, también en `Video.distanciaMetros`) y la da como "1.25 km" (punto), mientras la lista de videos usa la región ("1,25 km"). La fecha se invierte de `2026-10-09` a `09/10/2026`, igual que la lista.
- ⚠ **Rumbo negativo sale como "undefined":** la orientación (`Math.round(rumbo / 45) % 8` sobre `CARDINALES`) falla con valores negativos, y el acimut de `OrientationProvider` sale en −180…180 (11.2). La recolección debe guardar `rumbo` normalizado a 0…360. Deducido leyendo el código, no probado.
- El encuadre del mapa (`fitBounds`) se hace **solo la primera vez** que llega el video; editar (renombrar, eliminar foto) no lo mueve. "Mostrar otros videos" dibuja puntos grises `#64748b` solo con lat/lng.
- Accesibilidad web: marcadores con `title`, tira de fotos con `aria-label` y `aria-pressed`, tarjeta como región `aria-live`. Las miniaturas que fallan se ocultan (`onerror`).
- `abrirFoto` → `onAbrirImagen` (placeholder: falta 7.12).
- **Infraestructura compartida:** la fábrica del `WebView` (tamaño, fondo `#0A0E1A`, ajustes, depuración, consola, errores, `setInsets`, `BackHandler`) vive ahora en `map/MapaWebView.kt` (`MapaWebView` y `PuenteWeb`, ver 11.9). Aquí solo quedan `VideoPuente` y los `LaunchedEffect` que empujan `cargarOtros` y `cargarVideo`.
- El botón "Volver" de `NoEncontrado` es un `Button` estándar de Material: su alto mínimo (40 dp) queda bajo los 48 dp.

**UbicacionManual (vista 7.3; ⚠ código entregado el 2026-10-11, Kotlin sin compilar ni probar en dispositivo; `ui/admin/recoleccion/` y `assets/ubicacion_manual.*`)**

| Pieza | Detalle |
|---|---|
| `UbicacionManualViewModel` | `ViewModel(videos: VideoRepository, lugares: LugaresRepository)`; `Factory(appContext)` crea `AssetsVideoRepository` y `LugaresRepositoryStub` (**espera el contexto de la aplicación**). Estado en `ui: StateFlow<UbicacionManualUiState>`. Eventos por `Channel(BUFFERED)` + `receiveAsFlow()` (un solo colector; no se pierden). |
| `UbicacionManualUiState` | `lugares`, `punto: PuntoMapa?` (`null` hasta tocar el mapa), `rumbo` (0…360), `brujulaDisponible`, `usandoBrujula`, `cargandoUltima`, `ultimaPosicion: UltimaPosicion?`, `ultimaAplicada`, `nombreVideo`, `nombreSugerido`, `edicion: EdicionCoordenada?`, `centrarSolicitud: Int`, `confirmando`. Calculadas: `puedeConfirmar` (hay punto y no está confirmando), `latitudTexto`, `longitudTexto` (6 decimales, siempre con punto). |
| `UbicacionManualEvento` | Solo `Confirmado(inicio: InicioRecoleccion)`. **No navega.** |
| `UbicacionManualAcciones` | `data class` con 14 lambdas (`{}` por defecto): `onVolver`, `onAjustes`, `onPuntoCambiado(lat, lng)`, `onRumbo`, `onAlternarBrujula`, `onEditarCoordenada`, `onTextoEdicion`, `onAceptarEdicion`, `onCancelarEdicion`, `onUsarUltima`, `onNombre`, `onCancelar`, `onConfirmar`, `onCalibrar`. |
| `InicioRecoleccion` | `domain/model/InicioRecoleccion.kt`: `lat`, `lng`, `rumbo` (0…360), `nombreVideo` (recortado, nunca vacío) y `continuaVideoAnterior`. Es lo que debe recibir la vista 7.4. |
| Acciones del ViewModel | `alAbrir(brujulaDisponible)` (idempotente) · `alPausar()` (ON_STOP: apaga la brújula) · `alReanudar()` (ON_RESUME: reactiva «Confirmar») · `alMoverPunto(lat, lng)` · `alUsarUltimaPosicion()` · `alElegirRumbo(grados)` · `alAlternarBrujula()` · `alLeerBrujula(acimut)` · `alEditarCoordenada(campo)` · `alCambiarTextoEdicion` · `alAceptarEdicion()` · `alCancelarEdicion()` · `alCambiarNombre` · `alConfirmar()`. |
| Lógica pura (`internal`, sin Android) | `Rumbo` (`normalizar`, `diferencia`, `suavizar` —promedio exponencial **circular**—, `cardinal`, `nombreCardinal`), `parsearCoordenada(texto, limite)`, `siguienteNombre(videos)` y `calcularUltimaPosicion(videos)`. Se pueden probar sin emulador. |
| Constantes | `MAX_NOMBRE_VIDEO = 40`, `PREFIJO_VIDEO = "video_"`, `CampusMapa.CENTRO` (⚠ **aproximado**, EAFIT: solo es el encuadre inicial) y `CampusMapa.ZOOM_INICIAL = 17`. |

**Puente `UbicacionBridge`, web → app** (`@JavascriptInterface`, clase `UbicacionPuente : PuenteWeb`, `internal`; todo pasa al hilo principal): `listo()` (heredado), `puntoCambiado(lat, lng)` y `gesto(activo)`.
**App → web** (`mapa.js(...)`, solo tras `listo()`): `setCentro(lat, lng, zoom)`, `setPunto(lat, lng)`, `setRumbo(grados)`, `centrar()`, `zoomMas()`, `zoomMenos()` y `cargarLugares(texto)` (**texto** JSON entre comillas con `literalJs`; el JS hace `JSON.parse`). «Centrar» y +/− los dibuja Compose; el zoom de Leaflet está desactivado.

Comportamiento:
- **Un solo origen de verdad:** el punto vive en el ViewModel. El mapa avisa (`puntoCambiado`) al tocar y, mientras se arrastra, ~10 veces por segundo; el ViewModel lo reenvía con `setPunto`, que el JS **ignora mientras arrastra** (si no, el marcador temblaría).
- **Centrar el mapa:** solo cuando el punto cambia **desde fuera** del mapa (coordenadas editadas o «Usar mi última posición»): el ViewModel sube `centrarSolicitud` y la pantalla llama a `centrar()` (acerca a zoom ≥ 18).
- **Brújula:** `EscucharOrientacion` entrega acimut en −180…180; el ViewModel lo **normaliza**, lo suaviza y solo actualiza el estado si el cambio es ≥ 1,5°. Girar el dial a mano apaga la brújula. Es norte **magnético** (11.2).
- **Editar coordenadas:** si aún no hay punto, la otra coordenada se toma de `CampusMapa.CENTRO`. El diálogo usa `KeyboardType.Text` (no `Decimal`) porque algunos teclados numéricos no traen «−» y la longitud de Colombia es negativa.
- **Última posición:** el «último» video es el de mayor `creadoEn` (ISO-8601 ordena como texto; sin fecha, el último de la lista) y la última foto, la de mayor `capturadaEn`. Si `obtenerVideos()` falla, la fila queda deshabilitada y la vista sigue siendo usable.
- **Nombre autonumerado:** `video_(N+1)`, con N = mayor número entre los videos llamados `video3` / `video_3`…; si ninguno cumple el patrón, la cantidad de videos. Salta nombres ya usados.
- **Confirmar:** `confirmando` evita un doble toque; `alReanudar()` lo libera al volver a la pantalla (p. ej. desde 7.4).
- **Calibrar mi paso (7.3b):** `FilaCalibracion` (privada) va entre «Usar mi última posición» y el nombre del video. La pantalla lee `CalibracionPasoRepository(contexto).guardada()` con `remember` (`null` = valor genérico; se relee al volver porque `NavHost` recompone la ruta) y se la pasa al contenido; no está en el `UiState` ni en el ViewModel. Tocar la fila llama a `onCalibrar`, que la ruta conecta con `navigate("admin/calibracion")` (11.8).
- **Scroll vs. mapa:** el JS avisa `gesto(true/false)` en `touchstart` / `touchend` y la pantalla deshabilita `verticalScroll` mientras haya un dedo sobre el mapa. ⚠ Deducido, no probado: el aviso llega con un pequeño retraso.
- **Diseño adaptable:** la tarjeta de Orientación pone dial y botón lado a lado solo si `screenWidthDp >= 380` y `fontScale <= 1,15`; si no, los apila. (No usa `BoxWithConstraints`: no admite medidas intrínsecas dentro del `Row`.)
- **Reutiliza** `BotonIcono` y `Modifier.tarjeta` de `ui/destino/componentes/Comun.kt` (`internal`, mismo módulo). Por la regla 4 de 11, conviene moverlos a `ui/components/` cuando se toque.

Cuidados:
- ⚠ **Kotlin sin compilar.** Supuestos no verificados contra el código: los paquetes de `AssetsVideoRepository`, `LugaresRepositoryStub`, `VideoRepository` y `LugaresRepository` (`data.repository`), la firma de `BotonIcono` (`icono: ImageVector`), `MapaWebView`, `PuenteWeb.enHiloPrincipal`, `rememberMapaWeb` y `literalJs` (11.9), y `androidx.compose.ui.platform.LocalLifecycleOwner` (deprecado en versiones recientes de Compose).
- **No registra en `AppLog`** (su firma no está documentada aquí): un fallo al cargar videos o lugares no deja rastro. El mapa web usa `Log` con el tag `UbicacionMapa` (vía `MapaWebView`).
- **Sin internet** Leaflet (`unpkg.com`) no carga: la página muestra «No se pudo cargar el mapa…» y **no** llama a `listo()`, así que la app nunca le envía datos. Aun así se pueden escribir las coordenadas a mano y confirmar. Decisión abierta 13 (todo en línea).
- **Cancelar y atrás** hacen lo mismo (`onVolver`) y **no piden confirmación**: no hay nada guardado todavía.
- **Colores:** usa `CampusColors` salvo `ColorCancelar` (`#FF4D7D`, rosa del diseño; `CampusColors.Peligro` es morado, 11.4) y el fondo del mapa `#0A0E1A` (como los demás `WebView`).
- **Etiquetas «Latitud (X)» / «Longitud (Y)»** tal como en el diseño, aunque en rigor X es la longitud: valorar dejar solo «Latitud» y «Longitud».
- **Coordenadas con 6 decimales** (≈ 0,1 m); el diseño mostraba 4 (≈ 11 m), poco para anclar el dataset.
- Las etiquetas de lugares son **no interactivas**: tocar una coloca el punto donde está el dedo, no en las coordenadas del lugar (son aproximadas).
- Accesibilidad: el dial tiene descripción con grados y punto cardinal, acciones personalizadas (±15°, norte) y su leyenda visual oculta a TalkBack; «Usar mi última posición» es *live region* (anuncia «Posición tomada de …»); «Confirmar» deshabilitado dice «Falta marcar tu posición en el mapa». Botones de 48 dp o más (64 dp los de la barra inferior).
- **Previews:** 3 `@Preview` (con punto, sin punto y diálogo con error). El `WebView` no se previsualiza: se muestra un recuadro «Mapa (vista previa)» (`LocalInspectionMode`).
- **Prueba sin teléfono:** abrir `ubicacion_manual.html` en un navegador de escritorio activa un modo demo (3 lugares, punto y rumbo de ejemplo).

**`RecoleccionScreen` y `RecoleccionBridge` (vista 7.4; `ui/admin/recoleccion/` y `assets/recoleccion_mapa.*`)**

| Pieza | Detalle |
|---|---|
| `RecoleccionScreen` | `(onFinalizado: (ResumenRecoleccion) -> Unit, onDescartado: () -> Unit, onVolver: () -> Unit, onAjustes = {}, modifier, vm: RecoleccionViewModel = viewModel())`. **No navega**; la ruta decide (11.8). Es dueña de CameraX: crea el `ImageCapture` con `remember { crearImageCapture() }`, lo enlaza con `VistaCamara` (vista previa en la esquina del mapa), llama a `tomarFoto` en el evento `Capturar` y hace `liberarCamara(ctx)` y `keepScreenOn = false` al salir |
| Estados de la pantalla | `error` → texto «No se pudo iniciar la recolección» con «Volver»; `INICIANDO` → indicador de progreso; si no, columna con scroll: barra superior, aviso temporal, mapa (con «En vivo / Centrar», vista previa, +/− y leyenda), panel de re-anclaje (solo con el alfiler abierto), cuatro contadores, calidad, captura, Pausar / Reubicarme / Marcar punto, «Agregar alerta aquí», intervalo, «Finalizar video», alertas cercanas y panel de avisos |
| Diálogos y hojas | `AlertaFormSheet` cuando `ui.formularioAlerta != null` (siempre `esNueva = true`); selector de intervalo con `ModoCaptura.OPCIONES`; confirmación de finalizar (con 0 fotos avisa que el video se borrará) |
| `RecoleccionMapaContent` | `(control, lat, lng, rumbo: Float, fotosJson, trayectoriaJson, alertasJson, reanclaje: Pair<Double, Double>?, eventos, modifier)`. Solo dibuja el `WebView` (`MapaWebView` con `pasarInsets = false` y `manejarAtras = false`) y empuja el estado con `LaunchedEffect(mapa.listo, …)`. No conoce el ViewModel |
| `RecoleccionMapaControl` | `rememberRecoleccionMapaControl()`; `centrar()`, `zoomMas()`, `zoomMenos()` (botones que dibuja la pantalla, como en 7.3) |
| `RecoleccionMapaEventos` | `data class` con `onPuntoReanclaje(lat, lng)` (la pantalla lo conecta con `vm::alMoverReanclaje`) y `onSeguimiento(activo)` (resalta «En vivo» / «Centrar»); `{}` por defecto |
| `componentes/PanelesRecoleccion.kt` | Todo `internal`: `ChipEstadoVideo`, `TarjetaContador`, `TarjetaCalidad`, `TarjetaCaptura`, `BotonAccion`, `FilaAccion`, `BotonFinalizar`, `PanelReanclaje`, `FilaAlertasCercanas`, `PanelAvisos`, `formatearDistancia`, `formatearDuracion` y los colores `ColorFinalizar` (`#FF4D7D`) y `ColorAviso` (`#F59E0B`) |

**Puente `RecoleccionBridge`, web → app** (clase `RecoleccionPuente : PuenteWeb`, `internal`; todo pasa al hilo principal): `listo()` (heredado) · `puntoCambiado(lat, lng)` (solo con el re-anclaje abierto; arrastre ~10 veces por segundo o toque en el mapa) · `seguimientoCambiado(activo)`.
**App → web** (solo tras `listo()`): `setPosicion(lat, lng, rumbo)` · `cargarFotos(texto)` · `cargarTrayectoria(texto)` · `cargarAlertas(texto)` (los tres, **texto** JSON con `literalJs`; el JS hace `JSON.parse`) · `setReanclaje(lat, lng)` · `quitarReanclaje()` · `centrar()` · `zoomMas()` · `zoomMenos()`.
Formatos JSON: `fotosJson` = `[{id, lat, lng, rumbo|null}]`; `trayectoriaJson` = `[[lat, lng], …]`; `alertasJson` = los campos del editor (`id, lat, lng, mensaje, tipo, prioridad, radio, activa`).

Comportamiento y cuidados:
- **Atrás** (sistema y flecha): con error llama a `onVolver`; con el re-anclaje abierto lo cancela; si no, `alPedirFinalizar()`. `ON_STOP` → `alIrASegundoPlano()`.
- **Mapa:** sigue al admin (`panTo`) hasta que arrastra el mapa con el dedo; «Centrar» reactiva el seguimiento. La primera posición encuadra a zoom 19. Fotos y alertas se actualizan por `id` (el re-anclaje las desplaza). Con el alfiler abierto **no** se sigue al admin y se **ignoran los ecos** de `setReanclaje` mientras se arrastra (patrón de 7.3). Mensajes de alerta con `textContent`.
- **Usa `MapaBase.iniciar`** (a diferencia de 7.3). Como no tiene `#top`, `#dock` ni `#btn-back`, la página los incluye **ocultos** por si `mapa_base.js` no tolera que falten; si ya lo tolera, se pueden borrar. No define `setInsets` ni `onAtras` propio (los maneja la pantalla Compose).
- **Sin internet:** Leaflet (`unpkg.com`) no carga, `MapaBase.iniciar` avisa en pantalla y el mapa nunca llama a `listo()`; la grabación sigue funcionando sin mapa. Teselas de OSM, no satélite como el diseño (decisión 1 y 13).
- Las alertas se dibujan **todas igual** (ámbar si están activas, gris si no): no distinguen `tipo` ni `prioridad`. El CSS de la página duplica estilos de las otras páginas de mapa (candidato `mapa_base.css`). El centro inicial del JS es **aproximado** (EAFIT) y solo se ve antes del primer fix.
- **Prueba sin teléfono:** abrir `recoleccion_mapa.html` en un navegador de escritorio activa un modo demo (alguien camina en círculo, deja fotos y se ve una alerta).
- **Cámara:** la ruta la exige (11.8); la pantalla comprueba el permiso para activar `VistaCamara`. `VistaCamara` sigue sin manejar errores de `bindToLifecycle` (cuidado de 11.5).
- «Marcar punto de interés» está **deshabilitado**. El aviso temporal (`ui.aviso`) es una tarjeta propia que se descarta al tocarla; no usa `BannerEstado`. `ColorFinalizar` y `ColorAviso` son propios porque `CampusColors.Peligro` es morado (11.4).
- Reutiliza `BotonIcono` y `Modifier.tarjeta` de `ui/destino/componentes/Comun.kt` (`internal`): regla 4 de 11, conviene moverlos a `ui/components/`.
- Con fuente grande, los cuatro contadores en fila pueden apretarse. Sin brújula «N» ni giro del mapa.

**`CalibracionScreen` y `CalibracionBridge` (vista 7.3b; `ui/admin/calibracion/` y `assets/calibracion_mapa.*`; entregado el 2026-10-12, compila y se abre en dispositivo, ⚠ pasada completa sin probar)**

| Pieza | Detalle |
|---|---|
| `CalibracionViewModel(app)` | `AndroidViewModel` **sin `Factory`**. Crea su **propio** `PdrTracker` y un `CalibracionPasoRepository`. Salida: `ui: StateFlow<CalibracionUiState>`. Fases `FaseCalibracion`: `PUNTOS → LISTO → CAMINANDO → RESULTADO → GUARDADA` |
| Entradas del ViewModel | `alTocarMapa(lat, lng)` (1.º toque = A, 2.º = B; con ambos puestos se ignora: se arrastran; solo en `PUNTOS`/`LISTO`) · `alMoverPunto(ExtremoTramo, lat, lng)` · `alLimpiarPuntos()` · `alIniciar()` (fija la posición en A, `tracker.iniciar()`, anota `pasosInicio`, reloj de 500 ms) · `alFinalizar()` (lee `pasos − pasosInicio` **antes** de `detener()`, calcula con `CalibracionPaso.calcular` → `RESULTADO`) · `alCancelarMedicion()` · `alRepetir()` · `alGuardar()` (solo con `Valido` en `RESULTADO`) · `alRestablecer()` (vuelve a 0,72 m; no actúa en `CAMINANDO`) · `alIrASegundoPlano()` (ON_STOP: detiene el tracker y, si `CAMINANDO`, cancela con aviso) · `descartarAviso()` |
| `CalibracionUiState` | `fase`, `puntoA` / `puntoB` (`PuntoTramo(lat, lng)?`), `distanciaM`, `pasos`, `segundos`, `resultado`, `longitudActualM`, `calibrada`, `fuentePasos`, `aviso` (`AvisoCalibracion`, p. ej. `VALOR_RESTABLECIDO`, `CANCELADA_SEGUNDO_PLANO`). Calculadas: `puedeIniciar`, `hayPuntos`, `mapaBloqueado` (fuera de `PUNTOS`/`LISTO`), `pasosPorAcelerometro`. `ExtremoTramo`: `A`, `B` |
| `CalibracionScreen` | `(onVolver, modifier, vm: CalibracionViewModel = viewModel())`. **No navega**; la ruta pide `Permisos.ACTIVIDAD` antes de mostrarla (11.8). ON_STOP → `alIrASegundoPlano()`; Atrás durante la medición la cancela, si no → `onVolver`; `keepScreenOn` solo mientras `CAMINANDO` |
| `CalibracionContent` / `CalibracionAcciones` | Contenido sin lógica y `data class` de 11 lambdas (`{}` por defecto); 2 `@Preview` |
| `CalibracionMapaContent` | `(puntoA, puntoB, bloqueado, eventos: CalibracionMapaEventos, modifier)`. Solo dibuja el `WebView` (`MapaWebView` con `pasarInsets = false` y `manejarAtras = false`) y empuja el estado con `LaunchedEffect(mapa.listo, …)`. No conoce el ViewModel |

**Puente `CalibracionBridge`, web → app** (clase `CalibracionPuente : PuenteWeb`, `internal`; todo pasa al hilo principal): `listo()` (heredado) · `toque(lat, lng)` · `puntoMovido(extremo "A"|"B", lat, lng)` (solo al soltar el pin).
**App → web** (solo tras `listo()`): `setCentro(lat, lng, zoom)` (solo si aún no hay A) · `setPuntos(texto)` con `{"a": {lat, lng} | null, "b": …}` (**texto** JSON con `literalJs`) · `setBloqueado(bool)`.

Comportamiento y cuidados:
- El estado vive en el ViewModel; el JS **ignora `setPuntos` mientras se arrastra un pin** (patrón de 7.3) y encuadra el tramo al tener A y B por primera vez. Abrir `calibracion_mapa.html` en un navegador de escritorio activa un **modo demo**.
- **Usa `MapaBase.iniciar` y `MapaBase.crearMapa`** (11.9). ⚠ **No** `base.crearMapa`: ese error dejaba el mapa negro y sin aviso (Logcat: `base.crearMapa is not a function`). La página lleva ocultos `#top`, `#dock` y `#btn-back`.
- **Sin scroll:** el mapa ocupa el espacio sobrante (mín. 180 dp); con fuente muy grande en un teléfono pequeño el mapa se encoge y el resto puede recortarse. Usa el zoom nativo de Leaflet (abajo a la izquierda), no los botones +/− de Compose; el centro inicial es **aproximado** (EAFIT), no `CampusMapa.CENTRO`.
- **Sin internet** Leaflet (`unpkg.com`) no carga, el mapa nunca llama a `listo()` y **no se pueden marcar A y B**: la calibración es inutilizable sin mapa (decisión 13).
- El aviso de acelerómetro solo aparece tras el primer «Inicio» (la fuente de pasos se conoce al llamar a `iniciar()`).
- Una sola medición, sin promedio ni historial; se mide en línea recta A→B, sin compararla con la trayectoria del PDR.
- **Colores:** `CampusColors`, salvo `#FF4D7D` (Fin) y `#F59E0B` (avisos) propios, como en 7.4, porque `CampusColors.Peligro` es morado (11.4).
- Reutiliza `BotonIcono` y `Modifier.tarjeta` de `ui/destino/componentes/Comun.kt` (`internal`): regla 4 de 11, conviene moverlos a `ui/components/`. Los textos están fijos en español dentro del composable (sin recursos de strings).

**Componentes de `ui/ubicacion/componentes/` (verificados; propios de Escaneo, todos `internal`)**

| Componente | Firma | Qué hace / reutilización |
|---|---|---|
| `VistaCamara` | `(imageCapture: ImageCapture, activo: Boolean, modifier = Modifier)` | Vista previa de la cámara trasera (`PreviewView`, `FILL_CENTER`) en una caja negra de esquinas redondeadas con la etiqueta "Vista de cámara". Con `activo = true` hace `unbindAll()` y enlaza **vista previa + `imageCapture`** al `LocalLifecycleOwner`. Con `activo = false` solo muestra la caja negra. **Es la única que enlaza `crearImageCapture()`**: cualquier vista que use `tomarFoto` la necesita (o hacer ese enlace igual). Reutilizable tal cual por la recolección (7.4). |
| `AnilloProgreso` | `(estado: EscaneoUiState)` | Anillo de 0° a 360° (270×240 dp) con arco morado = grados girados (`estado.progreso`), una marca por foto cada `GRADOS_POR_FOTO` (72°, con check si ya se tomó) y, al centro, "Foto X de N" o "Analizando…" (`Fase.ANALIZANDO`). **No es reutilizable hoy**: depende de `EscaneoUiState`, `EscaneoConfig` y `EscaneoColores`. El 0° del anillo es **el inicio del giro**, no el norte. |
| `BarraSuperior` | `(onAtras, onAjustes)` | Volver + título fijo "Ubicarme" / "Captura de entorno" + Ajustes. Duplicada de la de Destino (ver arriba). |
| `InstruccionGrande` | `(texto: String, esError: Boolean)` | Ícono de 52 dp + texto de 28 sp. Con `esError` usa advertencia en rojo; si no, ícono de refrescar en morado. El ícono no se anuncia (el texto ya dice lo mismo). Genérica. |
| `RecordatoriosFijos` | `()` | Dos avisos fijos: "Más despacio" y "Mantén el celular vertical". Textos fijos. |
| `IndicadorInclinacion` | `(inclinacionOk: Boolean)` | Tarjeta verde ("Tu teléfono está en posición correcta") o roja ("Endereza el teléfono: mantenlo vertical"). El color no es la única señal: cambian ícono y texto. |
| `BotonesAccion` | `(onCancelar, onRepetir)` | "Cancelar" (relleno) y "Repetir" (contorno), de 60 dp de alto. Textos fijos. |

Cuidados de estos componentes:
- **Paleta propia:** usan `EscaneoColores` (`Fondo`, `Panel`, `Pista`, `Morado`, `MoradoBoton`, `MoradoClaro`, `Rojo`, `Verde`, `TextoSecundario`) y un gris fijo `#1F2937` para divisores y bordes, no `CampusColors`. Confirma la nota de 11.4.
- **`VistaCamara` no maneja errores:** si `bindToLifecycle` lanza excepción (sin cámara trasera, cámara en uso) ocurre dentro de un listener del hilo principal y **cierra la app**. Tampoco desenlaza al pasar `activo` a `false`: la cámara sigue enlazada hasta que se cierre el ciclo de vida o se llame a `liberarCamara(ctx)`.
- **`VistaCamara` enlaza una sola vez:** el bloque `factory` solo corre al entrar en composición; si se le pasa **otro** `ImageCapture` después, no se vuelve a enlazar. Crear el `ImageCapture` una vez (en el ViewModel o con `remember`).
- No pide el permiso de cámara: espera que la ruta ya lo haya resuelto (11.3).
- Los botones de icono de `BarraSuperior` son `IconButton` estándar (48 dp), por debajo de los 56 dp que piden las vistas públicas (11.1).
- `AnilloProgreso` anuncia siempre "Foto X de N", incluso durante "Analizando…"; y `IndicadorInclinacion` no se marca como *live region*, así que TalkBack no anuncia el cambio de estado por sí solo.

**Inicio (verificado: `ui/inicio/InicioViewModel.kt` e `InicioScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `InicioViewModel(app: Application)` | `AndroidViewModel`, sin `Factory`. Crea su propio `VoiceController` y lo libera en `onCleared`. Expone `estado: StateFlow<InicioUiState>` y `eventos: SharedFlow<InicioEvento>` (`extraBufferCapacity = 1`, `tryEmit`, sin `replay`). |
| `InicioUiState` / `InicioEvento` | `InicioUiState(escuchando = false, backendEnLinea = false)`. `InicioEvento`: `Ubicarme` e `IrALugar` (sin datos). |
| Acciones | `alAbrir()` · `alPresionarOrbe()` · `ubicarme()` · `irALugar()` · `alPausar()` · `explicarPermisos(alTerminar: () -> Unit)`. `BIENVENIDA` es una constante **pública** (`InicioViewModel.BIENVENIDA`). |
| `BackendHealth` | `interface` con `suspend estaEnLinea(): Boolean` y `object BackendHealthStub` (siempre `true`); ambos viven en `InicioViewModel.kt`, no en `data/repository/`. El ViewModel usa el stub **fijo** (`private val backend`): para conectar `GET /health` hay que cambiar esa línea. |
| `InicioScreen` | `(onUbicarme, onIrALugar, onAccesoAdministrador, viewModel = viewModel())`. Recoge `estado` con `collectAsStateWithLifecycle()`. |
| `InicioContent` | `(escuchando, backendEnLinea, permisosFaltantes: List<String>, onOrbe, onUbicarme, onIrALugar, onAccesoAdministrador, onReintentarPermisos, onIrAAjustes)`. Público, **sin `@Preview` ni `modifier`**. |

Flujo:
- Al entrar en composición: con los tres permisos concedidos llama a `alAbrir()` (dice `BIENVENIDA` y al terminar escucha). Si falta alguno llama a `explicarPermisos` (dice para qué se pide cada cosa) y al terminar lanza el diálogo del sistema; el resultado, **sea cual sea**, vuelve a llamar a `alAbrir()`.
- `escuchar()` → `ComandoParser.parse`: `UBICARME` / `IR_A_LUGAR` navegan; `NINGUNO` o fallo → `repetirOpciones()`: dice «No te entendí. …» y vuelve a escuchar. Al **3.er** fallo (`MAX_INTENTOS = 3`) dice «Presiona el botón central cuando quieras hablar.» y deja de escuchar. `intentos` solo vuelve a 0 en `alAbrir` y en `alPresionarOrbe`.
- `navegar()` (salida común): `voz.stopAll()`, `escuchando = false` y emite el evento.
- ON_STOP → `alPausar()` (`stopAll` + `escuchando = false`); ON_RESUME solo refresca la lista de permisos y **no** reanuda la escucha.
- Sondeo de conexión: en el `init`, bucle infinito cada 15 s con `runCatching { estaEnLinea() }` (una excepción cuenta como «sin conexión»). Corre mientras el ViewModel viva, también con la pantalla en segundo plano, y no tiene tiempo máximo: una llamada real que se cuelgue detiene el sondeo. `backendEnLinea` arranca en `false`: hay un instante de «Sin conexión» antes del primer resultado. Con el stub siempre dice «Conectado».

Pantalla:
- Orbe de 252 dp (rol botón) con pulso mientras `escuchando`; título de 28 sp que pasa a «Te escucho…»; indicador de señal decorativo; texto fijo «Activa el lector de pantalla»; barra inferior con el punto verde/rojo del backend y «Acceso administrador» (alto ≈ 48 dp).
- Accesibilidad del orbe: «Botón principal. Toca dos veces para iniciar el escaneo de 360 grados y saber dónde estás.» y una acción personalizada de TalkBack «Ir a un lugar». La descripción **no cambia** al escuchar y «Te escucho…» no es *live region*.
- `BannerPermisos` lista los faltantes con nombre legible («Cámara», «Micrófono», «Sensores de actividad») y dos acciones: «Permitir» (relanza el diálogo) y «Ajustes» (`ACTION_APPLICATION_DETAILS_SETTINGS`). La lista se refresca tras cada solicitud y al volver de Ajustes.

Cuidados:
- ⚠ **El orbe ya no escucha, navega.** `alPresionarOrbe()` va directo a Ubicarme (un comentario del código dice que antes hacía `stopAll(); escuchar()`). Consecuencias: (1) la spec 6.1 pide dos botones grandes («Ubicarme» e «Ir a un lugar»), un botón de micrófono y un botón de Ajustes; el código tiene **un solo orbe** y ninguno de los otros; (2) por toque solo se llega a «Ir a un lugar» con la acción de TalkBack; sin TalkBack hay que decir «dos»; (3) el texto en pantalla («Presiona para ubicarte o para llegar a un lugar») y el mensaje hablado tras 3 fallos («Presiona el botón central…») ya no corresponden a lo que hace el toque. Hay que decidir el diseño (decisión abierta); `ubicarme()` e `irALugar()` ya existen para dos botones.
- ⚠ **Doble solicitud de permisos (verificado en `MainActivity.kt`).** La ruta `inicio` muestra `PedirPermisos` **antes** de `InicioScreen` y descarta el resultado (11.8). Cuando por fin se compone la pantalla, o ya están todos (entra directo en `alAbrir()` y **la explicación hablada nunca suena**) o alguno quedó negado (suena la explicación y el diálogo se repite). Es la «explicación previa» que 6.1 y la sección 10 dan por pendiente: el código existe, pero nunca queda antes del primer diálogo. Para arreglarlo, la ruta no debería pedir nada y dejar que `InicioScreen` lo haga.
- Sin micrófono, `listen` responde `onFail` al instante (11.2): la pantalla dice «No te entendí…» tres veces y luego «Presiona el botón central…», sin explicar que falta el micrófono.
- ⚠ Sin token (11.2): un `alTerminar` encolado puede llamar a `escuchar()` justo después de `alPausar()` o `navegar()`.
- ⚠ `alAbrir()` se llama cada vez que la pantalla entra en composición (`LaunchedEffect(Unit)`), p. ej. al volver de Ubicarme: es de esperar que vuelva a leer la bienvenida (deducido, no probado).
- «Permitir» y «Ajustes» son `Text` con `clickable`: alto aproximado de 40 dp (16 sp + 10 dp arriba y abajo), **bajo los 48 dp** de 11.1.
- `BannerPermisos` duplica a `BannerEstado` (con colores propios) y no es *live region*: ⚠ TalkBack no lo anuncia al aparecer y puede leer el mensaje dos veces (descripción del contenedor + hijos).

**`SeleccionDestinoViewModel` (verificado, `ui/destino/SeleccionDestinoViewModel.kt`; la pantalla está en el bloque siguiente)**

| Pieza | Detalle |
|---|---|
| Construcción | `SeleccionDestinoViewModel(app: Application)`, sin `Factory`. Crea directamente `LugaresRepositoryStub()` y su propio `VoiceController(app)` (se libera en `onCleared`). |
| Salidas | `estado: StateFlow<DestinoUiState>` y `eventos: SharedFlow<DestinoEvento>` (`extraBufferCapacity = 1`, `tryEmit`: sin colector en ese instante el evento se pierde). Único evento: `DestinoEvento.Confirmado(lugar: LugarDestino)`. **No navega.** |
| `DestinoUiState` (`SeleccionDestinoState.kt`) | `cargando`, `error: ErrorDestino?` (`SIN_CONEXION`, `DESCONOCIDO`), `sinMicrofono`, `escuchando`, `textoReconocido: String?`, `candidato: LugarDestino?`, `opciones: List<LugarDestino>`, `busqueda`, `categoria: CategoriaLugar?`, `orden: OrdenLugares` (`CERCANIA`, `NOMBRE`) y `lugares` (ya filtrada y ordenada). Valores por defecto (verificado): `cargando = true`, `error = null`, `sinMicrofono = false`, `escuchando = false`, `textoReconocido = null`, `candidato = null`, `opciones = emptyList()`, `busqueda = ""`, `categoria = null`, `orden = CERCANIA`, `lugares = emptyList()`. **Archivo completo verificado (bache 1):** `ErrorDestino`, `OrdenLugares` y `DestinoEvento` van en el mismo archivo. `OrdenLugares(etiqueta)` lleva el texto de cada orden: `CERCANIA` = «Ordenado por cercanía» y `NOMBRE` = «Ordenado por nombre». `DestinoEvento` es una `sealed interface` con **un solo caso**, `Confirmado(lugar: LugarDestino)`: añadir otro evento obliga a ampliar el `when` de la pantalla. Convención del archivo: la UI solo **lee** `DestinoUiState` y el ViewModel es el único que lo escribe. `DestinoUiState` es una `data class` simple, sin `Parcelable` ni guardado propio. |
| Acciones | `alAbrir(microfonoDisponible)` · `reintentarCarga()` · `alPresionarMicrofono()` · `alElegirLugar(lugar)` · `alResponderSi()` · `alResponderNo()` · `descartarTexto()` · `alCambiarBusqueda(texto)` · `alElegirCategoria(categoria?)` · `alCambiarOrden()` · `limpiarFiltros()` · `alPausar()` · `alSalir()`. |
| Constantes y logs | `PREGUNTA` = «¿A dónde quieres ir? Di el nombre del lugar.» (pública) y `MAX_INTENTOS = 3` (privada). Tag `DestinoVM`: cantidad de lugares, «Voz: N coincidencia(s)» (**no** registra lo que se dijo), `id` del destino propuesto y confirmado, y el error de carga. |

Flujo:
- `alAbrir` es **idempotente** (bandera `iniciado`): solo cuenta la primera llamada; el micrófono se decide ahí (`conVoz`) y no se reevalúa si la persona lo concede después.
- Carga → (si hay voz) pregunta → `BuscarLugares.mejores` (reglas y ⚠ en 11.7): 0 → «No encontré ese lugar. Intenta de nuevo.»; 1 → `proponer`; 2–3 → «Encontré N lugares: A, B o C. Di cuál quieres.» y vuelve a escuchar.
- `proponer(lugar)` muestra la tarjeta (`candidato`), pregunta «¿Quieres ir a X? Di sí o no.» y, si hay voz, escucha: `SI` → `confirmar`; `NO` → `rechazar`; `NINGUNA` → repite (a los 3 fallos: «Usa los botones Sí o No cuando quieras.» y deja de escuchar).
- `rechazar` limpia texto, candidato y opciones, y pregunta «De acuerdo. ¿A qué lugar quieres ir?». `confirmar` hace `detenerVoz()`, registra y emite `Confirmado`.
- Sin micrófono (`conVoz = false`): no pregunta ni escucha, pero sí habla las confirmaciones al tocar un lugar; el micrófono de la pantalla solo dice «El micrófono no está disponible. Elige un lugar de la lista.»
- Lista: `refiltrar()` = `BuscarLugares.filtrar` + categoría + orden. `CERCANIA` ordena por `distanciaMetros` con los `null` al final (con el stub todos son `null`: queda el orden original). `NOMBRE` usa el orden normal de `String`, que distingue mayúsculas y tildes («Árbol» quedaría después de «Zeta»).

Cuidados:
- `intentosDestino` solo vuelve a 0 en `alPresionarMicrofono` (al empezar a escuchar) y en `rechazar`; **no** tras un reconocimiento correcto ni al elegir de la lista. `intentosConfirmacion` solo se reinicia en `proponer`: tras 3 fallos, un toque en el micrófono escucha **una sola vez** y, si falla, repite «Usa los botones…».
- `alCambiarBusqueda` **corta la voz** en cada tecla; cambiar categoría, orden o limpiar filtros **no**.
- `alElegirCategoria(categoria)` solo asigna. El comentario dice «si ya estaba activo, lo quita», pero **el ViewModel no hace ese conmutador**: quien llama debe pasar `null` al tocar el chip activo. La pantalla lo pasa tal cual (`onCategoria = viewModel::alElegirCategoria`), y el conmutador está en `FilaCategorias`: tocar un chip destacado activo pasa `null` (verificado, bache 2).
- Un error de carga que no es `IOException` (`DESCONOCIDO`) también dice «Revisa tu conexión y toca reintentar».
- ⚠ **Estado viejo al volver** (verificado en el código de la ruta, el ViewModel y la pantalla; no probado en dispositivo): `candidato` no se limpia al confirmar y `iniciado` sigue en `true`. Como la ruta `destino` navega a `ubicarme` **sin quitarse de la pila** (11.8), al terminar el escaneo `popBackStack()` vuelve a Destino con el mismo ViewModel: la pantalla vuelve a llamar `alAbrir`, que se ignora, así que no repite la pregunta, la tarjeta de confirmación sigue visible y otro «Sí» emitiría `Confirmado` de nuevo. Arreglo mínimo: poner `candidato = null` (y `opciones`) al confirmar, o reiniciar `iniciado` en `alPausar`.
- `onCleared` solo sube el `token` y libera la voz (no llama a `detenerVoz()`).

**`SeleccionDestinoScreen` (verificado, `ui/destino/SeleccionDestinoScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `SeleccionDestinoScreen` | `(onVolver, onDestinoConfirmado: (LugarDestino) -> Unit, onAjustes = {}, viewModel = viewModel())`. Recoge `estado` con `collectAsStateWithLifecycle()`. Solo conecta: micrófono, eventos, ciclo de vida y «atrás». |
| `SeleccionDestinoContent` | `(estado: DestinoUiState, acciones: DestinoAcciones)`. Público, con un `@Preview` privado (`PreviewSeleccionDestino`: escuchando, texto «biblioteca», candidato y 4 lugares de `LUGARES_DE_PRUEBA`). |
| `DestinoAcciones` | `class` pública (no `data class`, **sin valores por defecto**) con 12 lambdas: `onVolver`, `onAjustes`, `onMicrofono`, `onDescartarTexto`, `onSi`, `onNo`, `onElegirLugar`, `onCategoria`, `onBusqueda`, `onCambiarOrden`, `onLimpiarFiltros`, `onReintentar`. |

Conexión:
- **Micrófono:** `remember { checkSelfPermission(RECORD_AUDIO) == GRANTED }` y `viewModel.alAbrir(microfonoOk)` en `LaunchedEffect(Unit)`. No pide el permiso (lo pide la ruta de Inicio).
- **Eventos:** `Confirmado(lugar)` → `onDestinoConfirmado(lugar)`.
- **Salir:** ON_STOP → `alPausar()`. El «atrás» del sistema (`BackHandler`), la flecha de `BarraSuperior` y `BotonVolver` pasan todos por `salir = { alSalir(); onVolver() }`.
- `acciones` se crea con `remember(viewModel)`: captura `salir` y `onAjustes` de la **primera** composición; si el padre cambia esas lambdas, no se actualizan.

Orden del contenido (un solo `LazyColumn`): `EncabezadoPregunta` → `ZonaMicrofono` → si `sinMicrofono`, `BannerEstado` de advertencia «Sin micrófono» → `TarjetaTextoReconocido` (si hay texto) → `TarjetaConfirmacion` (si hay `candidato`) → `TarjetaOpciones` (solo si **no** hay candidato y sí opciones) → `FilaCategorias` → `CampoBusqueda` → `EncabezadoLista` → **una** de: cargando (`CircularProgressIndicator`), error, vacío («No hay lugares con estos filtros» + «Limpiar filtros») o la lista de `FilaLugar`. `BotonVolver` queda fijo abajo, fuera de la lista. Usa `statusBarsPadding`, `navigationBarsPadding`, `imePadding` y `CampusColors.Fondo`.

Cuidados:
- **El error es siempre «Sin conexión / No se pudo cargar la lista de lugares.»** con «Reintentar», aunque el `ErrorDestino` sea `DESCONOCIDO`.
- La lista usa `key = { it.id }`: los `id` de `LugarDestino` deben ser **únicos**; con repetidos Compose lanza una excepción.
- Las tarjetas de texto, confirmación y opciones viajan **dentro** del mismo `LazyColumn` que la lista: si quien ve se desplaza hacia abajo, la confirmación sale de pantalla (a quien usa voz no le afecta).
- Las firmas de 11.5 de `ZonaMicrofono`, `TarjetaTextoReconocido`, `TarjetaConfirmacion`, `BarraSuperior`, `FilaCategorias`, `CampoBusqueda`, `EncabezadoLista`, `FilaLugar`, `EstadoVacio` y `BotonVolver` **coinciden** con cómo las llama esta pantalla y con los propios archivos de `componentes/` (bache 2); lo mismo vale para `EncabezadoPregunta` y `TarjetaOpciones`.

**Login (verificado, `ui/auth/LoginViewModel.kt` y `LoginScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `LoginViewModel` | `ViewModel(auth: AuthRepository, session: SessionManager)`. Su `Factory(context)` convierte a `applicationContext` por sí sola y **fija** `AuthRepositoryStub()`: para el backend real se cambia ahí. Expone `state: StateFlow<LoginUiState>` y `eventos` (`Channel(BUFFERED)` + `receiveAsFlow()`: un solo colector; sin colector el evento espera, no se pierde). |
| `LoginUiState` | `identificador`, `password`, `mostrarPassword = false`, `cargando = false`, `error: LoginError? = null`. Calculada `puedeEnviar` = identificador no vacío (`isNotBlank`) **y** contraseña no vacía (sin recortar) **y** `!cargando`. |
| `LoginError` | `CredencialesInvalidas`, `SinConexion`, `SinPermisos`, `Desconocido`. El texto que ve la persona lo decide la pantalla (tabla más abajo). |
| `LoginEvento` | Solo `IrAlPanel`. |
| Acciones | `onIdentificadorChange(valor)` y `onPasswordChange(valor)` (ambas borran el error) · `onTogglePassword()` · `iniciarSesion()`. |

`iniciarSesion()`:
1. Si `!puedeEnviar` no hace nada (un doble toque se ignora mientras `cargando`).
2. Llama a `auth.login(identificador.trim(), password)`.
3. `ADMIN` → `session.guardar(sesion)`, vacía `password` y emite `IrAlPanel`.
4. Cualquier otro rol → `session.cerrarSesion()` (**borra también una sesión que ya existiera**), vacía `password` y `error = SinPermisos`.
5. `CredencialesInvalidasException` → `CredencialesInvalidas`; `IOException` → `SinConexion`; cualquier otra `Exception` → `Desconocido`.

Cuidados:
- En el `init`, si `session.esAdmin()` ya es `true` emite `IrAlPanel` (entra directo al panel). Corre en el hilo principal **sin `try/catch`** (ver 11.3). Como `MyApp` borra la sesión en cada arranque en frío, el atajo solo ocurre con el proceso vivo (p. ej. volver al modo público desde el panel y pulsar «Acceso administrador»).
- `catch (e: Exception)` también atrapa `CancellationException` (no la relanza) y los fallos de `session.guardar`: salen como `Desconocido`. No hay `AppLog`: ningún error de login deja rastro (bien para contraseña y token, pero `Desconocido` no se puede diagnosticar).
- Tras un login correcto solo se vacía `password`; `identificador` queda en el estado.

**`LoginScreen` (verificado, `ui/auth/LoginScreen.kt`)**

| Pieza | Detalle |
|---|---|
| `LoginScreen` | `(onLoginExitoso, onVolver, viewModel = viewModel(factory = LoginViewModel.Factory(LocalContext.current.applicationContext)))`. Recoge `state` con `collectAsStateWithLifecycle()` y convierte `LoginEvento.IrAlPanel` en `onLoginExitoso()`. No tiene `BackHandler`: el «atrás» del sistema lo resuelve el `NavHost`. |
| `LoginContent` | `(state: LoginUiState, onIdentificadorChange, onPasswordChange, onTogglePassword, onIniciarSesion, onVolver)`. **`internal`**, con 4 `@Preview` privados. |

Cada `LoginError` se dibuja con `BannerEstado` (11.5):

| `LoginError` | Tipo | Título | Mensaje |
|---|---|---|---|
| `CredencialesInvalidas` | Error | «Credenciales inválidas» | «El usuario o la contraseña son incorrectos.» |
| `SinConexion` | Advertencia | «Sin conexión» | «No se puede conectar con el servidor. Verifica tu conexión a internet.» |
| `SinPermisos` | Error | «Sin permisos» | «Tu cuenta no tiene rol de administrador, por eso no se habilita el panel.» |
| `Desconocido` | Error | «Algo salió mal» | «No pudimos iniciar sesión. Inténtalo de nuevo.» |

Comportamiento:
- **Carga:** `IndicadorCarga` («Verificando credenciales…») con `liveRegion = Polite` y `mergeDescendants`. Mientras `cargando` los dos campos quedan **deshabilitados** y el botón por `puedeEnviar`. Carga y error son excluyentes y comparten una zona con `animateContentSize`.
- **Teclado:** el usuario es `KeyboardType.Email` con `ImeAction.Next` (pasa al campo de contraseña); la contraseña es `Password` con `Done`, que quita el foco y llama a `onIniciarSesion()` (el ViewModel vuelve a comprobar `puedeEnviar`). El botón del ojo mide 56 dp y se anuncia «Mostrar contraseña» / «Ocultar contraseña».
- **Tamaños:** campos y «Iniciar sesión» de 68 dp o más; «Volver al inicio» de 64 dp o más. La pantalla se desplaza (`verticalScroll` + `heightIn(min = maxHeight)`), con `systemBarsPadding` e `imePadding`; «Volver» queda abajo gracias a un `Spacer` con peso.
- **Accesibilidad:** el título «Campus Navi» lleva `heading()` y el logo la descripción «Logo de Campus Navi». Las etiquetas son el `label` de cada campo.

Cuidados:
- ⚠ **Nombre del producto:** la pantalla se llama «Campus Navi» (título y logo) y este documento «Campus Locator». Hay que decidir uno.
- Paleta privada, casi toda igual a `CampusColors` (11.4).
- Los dos campos pierden el foco (y el teclado se cierra) al empezar la carga, porque se deshabilitan; tras un error hay que volver a tocar el campo.
- Faltan `@Preview` para `SinPermisos`, `Desconocido` y contraseña visible.

### 11.6 Datos: repositorios y modelos

Convención: `interface XRepository` + `XRepositoryStub` (o `AssetsX` si lee de `assets/`) + TODO `RemoteX`
con Retrofit/Ktor y `ApiConfig.kt`. Los ViewModels de hoy crean el stub directamente (verificado: `SeleccionDestinoViewModel` con `LugaresRepositoryStub()`, `InicioViewModel` con `BackendHealthStub`, y las `Factory` de Login y Lista de videos con `AuthRepositoryStub()` y `AssetsVideoRepository`): para pasar al backend se cambian esas líneas, no las pantallas.

| Repositorio | Métodos | Estado | Usado por |
|---|---|---|---|
| `AuthRepository` | `suspend login(identificador: String, password: String): Sesion` (lanza `CredencialesInvalidasException` o `java.io.IOException`) | Stub (`AuthRepositoryStub`) | `LoginViewModel` (por `Factory`) |
| `AdminRepository` | `suspend obtenerResumen(): ResumenAdmin` (lanza `IOException`, solo documentado en el KDoc) | Stub (`AdminRepositoryStub`, 600 ms) | `PanelAdminViewModel` (por `Factory`). Detalle abajo |
| `VideoRepository` | `suspend obtenerVideos(): List<Video>` (cada `Video` ya trae sus `fotos`) · `suspend renombrarVideo(videoId, nombre)` · `suspend eliminarVideo(videoId)` · `suspend eliminarFoto(videoId, fotoId)` · `cambios(): Flow<Int>` | Local (`AssetsVideoRepository(context)`) | Galería, Lista y Detalle de video |
| `RecoleccionRepository` | `crearVideo(inicio): String` · `carpetaFotos(videoId): File` · `registrarFoto(videoId, archivo, DatosFoto): FotoRecolectada` · `desplazarFotos(videoId, desdeIndice, dLat, dLng)` · `fotos(videoId)` · `finalizar(videoId, duracionS, distanciaM, pasos): ResumenRecoleccion` · `descartar(videoId)` · `buscarEnCurso(): String?` · `contarPendientes(): Int` · `marcarSubida(videoId, fotoIds)` · `espacioLibreBytes(): Long` | Local (`RecoleccionRepositoryLocal(context)`, `data/repository/RecoleccionRepository.kt`) | `RecoleccionViewModel` (lo crea directamente). Detalle abajo |
| `CalibracionPasoRepository` | `guardada(): Double?` · `longitudPasoM(): Double` (la calibrada, o `PdrEngine.LONGITUD_PASO_DEFECTO_M`) · `guardar(Valido, ahoraMs = ahora)` · `restablecer()` (borra todo el archivo) | Local (`CalibracionPasoRepository(context)`, `data/repository/CalibracionPasoRepository.kt`; **sin interfaz**) | `PdrTracker` (valor por defecto del parámetro), `CalibracionViewModel` y `UbicacionManualScreen`. Detalle abajo |
| `LugaresRepository` | `suspend obtenerLugares(): List<LugarDestino>` (lanza `IOException`, solo documentado en el KDoc) | Stub (`LugaresRepositoryStub`, 300 ms; devuelve `LUGARES_DE_PRUEBA`, 6 lugares) | `SeleccionDestinoViewModel` (lo crea directamente); futuras 6.3 y 7.6/7.7 |
| `EscaneoBackend` | `suspend analizar(fotos: List<File>)` → `Unit` (lanza `IOException`). Vive en `ui/ubicacion/EscaneoBackend.kt`, **no** en `data/repository/` | Stub (`EscaneoBackendStub`, 2,5 s) | `EscaneoViewModel` (lo instancia directamente). Detalle en 11.2 |
| `BackendHealth` | `suspend estaEnLinea(): Boolean`. Vive en `ui/inicio/InicioViewModel.kt`, **no** en `data/repository/` | Stub (`BackendHealthStub`, siempre `true`) | `InicioViewModel` (lo fija en una propiedad). Detalle en 11.5 |

| Modelo | Archivo | Notas |
|---|---|---|
| `Usuario`, `Rol`, `Sesion` | `domain/model/Usuario.kt` | Verificado (bache 3). `Rol` = `USER` / `ADMIN`; `Usuario(id, nombre, correo, rol)`; `Sesion(token, usuario)`. ⚠ El `toString()` de `Sesion` incluye el token. Detalle abajo |
| `ResumenAdmin` | `domain/model/ResumenAdmin.kt` | Verificado (bache 3): 6 campos, 5 datos del panel (el último video usa número y fecha). Detalle abajo |
| `Alerta`, `Lugar(nombre, lat, lng)` | `domain/model/Alerta.kt` | Detalle abajo. `Lugar` lo usa el editor de mapa |
| `LugarDestino`, `CategoriaLugar` | `domain/model/LugarDestino.kt` | Verificado contra el código. `id`, `nombre`, `categoria`, `lat`, `lng`, `alias`, `distanciaMetros?`, `imagenUrl?`. Detalle más abajo |
| `Foto`, `Video`, `EstadoFoto`, `CalidadFoto` | `domain/model/Foto.kt` | Detalle abajo. Ver también 7.11 y 7.14 |
| `InicioRecoleccion` | `domain/model/InicioRecoleccion.kt` | `lat`, `lng`, `rumbo` (0…360, 0 = norte; norte magnético si vino de la brújula), `nombreVideo` y `continuaVideoAnterior`. Lo emite la vista 7.3 y lo consume la 7.4 a través de `SesionDeRecoleccion`. Detalle en 11.5 («UbicacionManual») |
| `FotoRecolectada`, `DatosFoto`, `ResumenRecoleccion` | `domain/model/FotoRecolectada.kt` | Lo que guarda y devuelve `RecoleccionRepository`. `FotoRecolectada` tiene un `uid`. Detalle abajo |
| `SesionDeRecoleccion` | `domain/model/SesionRecoleccion.kt` (`object`) | Holder en memoria entre 7.3, 7.4 y 7.5. Detalle abajo |

**`AuthRepository` en detalle (verificado)**

- `CredencialesInvalidasException` (mensaje "Credenciales inválidas") vive en el mismo archivo. Contrato para el backend: `POST /auth/login` → token + rol; **401/403 por credenciales** → `CredencialesInvalidasException`; sin conexión o sin respuesta → `IOException`. ⚠ El contrato **no dice qué hacer con errores 5xx u otros códigos**: `RemoteAuthRepository` debe decidirlo (lo razonable es `IOException`). Verificado en `LoginViewModel`: una `IOException` se muestra como «sin conexión» y **cualquier otra** excepción como `LoginError.Desconocido` (11.5).
- Un login correcto devuelve la `Sesion` también para un usuario `USER`: **es el `LoginViewModel` quien decide no guardarla** (7.1). El repositorio no filtra por rol.
- **Cuentas del stub** (`AuthRepositoryStub`, espera simulada de 1,2 s; la contraseña se ignora): `admin@campus.edu.co` → `ADMIN`; `user@campus.edu.co` → `USER`; `offline` → `IOException`; cualquier otro → credenciales inválidas. Se compara el identificador sin espacios y en minúsculas, pero `correo` queda como lo escribió la persona. Cuidado: el stub devuelve `nombre = "Administrador"` y `token = "stub-token"` incluso para `USER`; no usar ese nombre en pruebas de interfaz.
- Nunca registrar `password` ni `token` en `AppLog`.

**`Alerta` y `Lugar` en detalle (verificado)**

| Campo de `Alerta` | Tipo y valores |
|---|---|
| `id`, `lat`, `lng`, `mensaje` | Obligatorios |
| `tipo` | `String`, por defecto `"otro"`. Claves del mapa web: `agua`, `mobiliario`, `escalones`, `obra`, `vehiculos`, `otro` |
| `prioridad` | `String`, por defecto `"normal"`. Valores: `normal`, `alta` |
| `radio` | `Int` en metros, por defecto `15`; el rango válido es 5…100 |
| `activa` | `Boolean`, por defecto `true` |

- `tipo` y `prioridad` son **texto libre, no enums**, y el modelo **no valida** el rango del radio: un error de escritura pasa sin aviso y el mapa web no reconocería la clave. Validar en el formulario (7.9) o convertirlos en enums con las mismas claves.
- `Alerta` no guarda quién la creó ni cuándo.
- `Lugar(nombre, lat, lng)` no tiene `id` ni categoría; `LugarDestino` sí. Esa diferencia es lo que hay que resolver al unificarlos (ver la advertencia de `Lugar` y `LugarDestino` más abajo).

**`VideoRepository` en detalle (verificado)**

- **No hay `obtenerVideo(id)` ni `obtenerFotos`:** todo sale de `obtenerVideos()`, que relee **todos** los manifests en `Dispatchers.IO`. Para un solo video (Detalle) se filtra por `id` en la lista; no llamarlo en cada recomposición.
- **Videos** ordenados por nombre de carpeta; **fotos** de cada video ordenadas por `id` como **texto**: los ids deben ir con ceros a la izquierda (`"0001"`, `"0002"`…); `"10"` quedaría antes que `"9"`. Un video cuyo manifest falla se **omite** (queda un `Log.w`, no una excepción).
- **`cambios(): Flow<Int>`** devuelve el contador de `EdicionesLocales` (un `StateFlow` por dentro): emite el valor actual **apenas se empieza a recoger**. Si el ViewModel carga datos y además recoge `cambios()`, la carga inicial ocurre dos veces salvo que se ignore la primera emisión. El número no significa nada; solo avisa de que "algo cambió, vuelve a pedir".
- **`EdicionesLocales`** (`internal object`): renombrar y eliminar viven **en memoria** y se aplican encima de lo leído de `assets/`; se pierden al cerrar la app. Al renombrar un video, también cambia `videoNombre` en todas sus fotos. Desaparece con el backend (**TODO** `RemoteVideoRepository`).
- **Cómo lo consumen hoy las vistas:** Detalle de video recoge `cambios()` y es la referencia (ver `VideoDetalleViewModel`, 11.5). Galería carga una sola vez, no recoge `cambios()` y sus eliminar/reasignar **no** pasan por el repositorio (ver `GaleriaViewModel`, 11.5). Lista de videos también recoge `cambios()` desde su `init` (ver `VideosViewModel`, 11.5).
- **Lo que falta para ver lo recolectado:** la recolección (7.4) **no** usa `VideoRepository`: guarda con `RecoleccionRepository` (abajo), así que lo que se recolecta no aparece en Galería, Lista ni Detalle de video. Hace falta un `VideoRepository` **compuesto** (assets + `files/recoleccion/`) y un parser de manifest compartido. Esto cambia lo que pedía este documento (ampliar `VideoRepository` con `crearVideo` y `agregarFoto`): la interfaz sigue siendo de **solo lectura + borrar/renombrar**.
- **Formato del `manifest.json` que lee hoy el código:** `name` (si falta, usa el nombre de la carpeta), `created_at`, `photos[]` con `id`, `file`, `lat`, `lng` (obligatorios) y `thumb`, `heading`, `captured_at`, `lugar`, `estado`, `calidad` (opcionales). ⚠ **El código no lee `video_id`**: el id del video es el **nombre de la carpeta**, aunque la tabla de 7.11 lo menciona. `estado` y `calidad` se comparan con el **nombre** del enum sin importar mayúsculas (`"alta"`, `"ERROR"`), no con la etiqueta visible, y si falta o no se reconoce usan `PROCESADA` / `NORMAL`.
- Las URLs que arma son `file:///android_asset/videos/<id>/<ruta>`; si la miniatura no existe en `thumbs/`, `urlMiniatura` es la foto original.

**`RecoleccionRepository` y `SesionDeRecoleccion` en detalle** (entregado el 2026-10-11; compila y funciona, sin pruebas automáticas)

- **Por qué es aparte de `VideoRepository`:** éste es la fuente de verdad (futuro `RemoteVideoRepository`); el almacenamiento local de la captura es otra responsabilidad y así no se toca lo que ya funciona.
- **Carpeta:** `files/recoleccion/<rec_NNNN>/photos/NNNN.jpg` + `manifest.json`. El id del video es `rec_` + 4 dígitos (prefijo distinto de `vid_` para no chocar con los datos de prueba); el id de cada foto lleva 4 dígitos con ceros a la izquierda, para ordenar como texto (ver `VideoRepository`).
- **Manifest:** usa las claves del formato de `assets/videos/` (`video_id`, `name`, `created_at`, `photos[].id`, `file`, `lat`, `lng`, `heading`, `captured_at`) más claves **propias que el lector actual ignora**: `estado` (`en_curso` / `finalizado`), `start_lat`, `start_lng`, `start_heading`, `ended_at`, `duration_s`, `distance_m`, `steps` y `photos[].sync` (`pendiente` / `subida`). Es compatible **solo en las claves**: `AssetsVideoRepository` lee de `assets/`.
- **Fechas** en ISO-8601 (`yyyy-MM-dd'T'HH:mm:ssXXX`): ordena como texto (decisión pendiente de la nota de `Video.creadoEn` en 7.14).
- **`registrarFoto`** recibe el JPG que dejó `tomarFoto` (`tmp_<n>.jpg`), lo renombra a `NNNN.jpg` y actualiza el manifest en cada foto (se guarda de forma continua). `desplazarFotos` mueve de forma uniforme las fotos desde un índice (re-anclaje). `finalizar` marca el video como `finalizado` y devuelve el `ResumenRecoleccion`; `descartar` borra la carpeta. `buscarEnCurso`, `contarPendientes` y `marcarSubida` son para retomar y para la subida futura (**aún sin usar**). `espacioLibreBytes` alimenta el aviso de almacenamiento.
- Usa `org.json` (disponible en Android; en pruebas unitarias JVM hace falta la dependencia).
- **`SesionDeRecoleccion`** (`object`): `inicio: StateFlow<InicioRecoleccion?>` · `resumen: StateFlow<ResumenRecoleccion?>` · `iniciar(inicio)` (la llama 7.3 vía `AppNav`) · `consumirInicio()` (la llama 7.4; **devuelve y borra**) · `finalizar(resumen)` (la llama `AppNav` al terminar; la leerá 7.5) · `limpiar()`. Vive en memoria: se pierde si Android mata el proceso (7.4 muestra entonces `SIN_INICIO`).

**`CalibracionPasoRepository` en detalle** (entregado el 2026-10-12; la lógica pura de `CalibracionPaso` se verificó con kotlinc; el repositorio depende de Android y no se probó por separado)

- **Almacén:** `SharedPreferences` `campus_calibracion` (sin cifrar; no es un dato sensible). Claves: `longitud_paso_m`, `pasos`, `distancia_m`, `fecha_ms`. No hay un almacén genérico de preferencias (`SessionManager` es solo de sesión).
- `longitudPasoM()` es lo que lee `PdrTracker` al crearse; un valor guardado **fuera de 0,40–1,20 m se ignora** y se usa el genérico. `restablecer()` borra todo el archivo. `guardar` solo acepta un `ResultadoCalibracion.Valido`.
- La fuente de pasos es única (acelerómetro, `FuentePasos.ACELEROMETRO`), así que ya no hay que guardar con cuál se calibró. **Las calibraciones hechas antes del 2026-10-12 (sensor de hardware) deben rehacerse.**
- Sin interfaz ni `Remote…`: la calibración es **por dispositivo** y no se sincroniza con el backend.

**Modelos de `Foto.kt` (verificado)**

| Modelo | Campos y reglas |
|---|---|
| `EstadoFoto(etiqueta)` | `SUBIDA` "Subida" · `PROCESADA` "Procesada" · `ERROR` "Error" |
| `CalidadFoto(etiqueta)` | `ALTA` "Alta calidad" · `NORMAL` "Normal" · `BAJA` "Baja calidad" |
| `Foto` | `id` (único **solo dentro del video**), `videoId`, `videoNombre`, `urlFoto`, `urlMiniatura`, `lat`, `lng`, `rumbo: Float?` (grados, 0 = norte, sentido horario; `null` si se desconoce), `capturadaEn: String?`, `lugar: String?`, `estado` (por defecto `PROCESADA`), `calidad` (por defecto `NORMAL`). Calculadas: `uid` = `"videoId/id"` (**usarla como clave** en selecciones, listas y `key` de Compose, porque `id` se repite entre videos) y `nombreArchivo` (último tramo de `urlFoto`). |
| `Video` | `id`, `nombre`, `creadoEn: String?`, `fotos: List<Foto>`. `distanciaMetros` (calculada): suma haversine entre fotos consecutivas **en el orden de la lista**; con menos de 2 fotos vale `0.0`. |

- `capturadaEn` y `creadoEn` son **texto tal cual viene del manifest**: nadie los convierte a fecha todavía. Definir el formato (ISO-8601) antes de ordenar o filtrar por fecha.
- La función haversine (`distanciaEntre`) es **`private`**: si otra pieza necesita distancia entre coordenadas (seguimiento, `LugarDestino.distanciaMetros`), hay que extraerla a algo como `domain/util/Geo.kt` en vez de copiarla. No confundir `Video.distanciaMetros` (longitud del recorrido) con `LugarDestino.distanciaMetros?` (distancia desde la persona).

**`LugarDestino` y `CategoriaLugar` en detalle (verificado, bache 1)**

- `LugarDestino` es una `data class` inmutable (para cambiar algo, `copy(...)`). Obligatorios: `id: String`, `nombre: String`, `categoria: CategoriaLugar`, `lat: Double` y `lng: Double`. Con valor por defecto: `alias: List<String> = emptyList()`, `distanciaMetros: Int? = null` e `imagenUrl: String? = null`.
- `alias` son otros nombres que la persona puede decir (p. ej. «biblioteca», «los trillizos») y alimentan `BuscarLugares` (11.7): cuantos más alias cubran cómo habla la gente, mejor acierta la voz.
- `distanciaMetros` son **metros enteros desde la posición actual**; `null` si aún no hay ubicación. Depende de la posición, no del lugar. Al ser `data class`, dos copias del mismo lugar con distinta distancia **no son iguales** (`equals`): comparar lugares por `id`.
- `imagenUrl` es una URL o `file:///android_asset/...`; si es `null`, la lista muestra el ícono de la categoría.
- `CategoriaLugar` tiene 8 valores. `etiqueta` va en singular (filas de la lista y filtro de texto de `BuscarLugares.filtrar`) y `etiquetaPlural`, en los chips de filtro:

| Valor | `etiqueta` | `etiquetaPlural` | Grupo |
|---|---|---|---|
| `BIBLIOTECA` | Biblioteca | Biblioteca | destacada |
| `CAFETERIA` | Cafetería | Cafetería | destacada |
| `BANO` | Baño | Baños | destacada |
| `BLOQUE` | Bloque | Bloques | destacada |
| `AUDITORIO` | Auditorio | Auditorios | otra |
| `DEPORTES` | Deportes | Deportes | otra |
| `ADMINISTRACION` | Administración | Administración | otra |
| `ENTRADA` | Entrada | Entradas | otra |

- `CategoriaLugar.DESTACADAS` = Biblioteca, Cafetería, Baño y Bloque: según el comentario del código, las que tienen chip propio en 6.4. `OTRAS` = el resto (`values()` sin las destacadas); según el mismo comentario van en el menú «Más». Una categoría nueva entra en `OTRAS` sola. Verificado en el bache 2: `FilaCategorias` dibuja `DESTACADAS` como chips y `OTRAS` en el menú «Más» (11.5), y `CategoriaLugar.icono()` (`Comun.kt`) es un `when` exhaustivo sin `else`: una categoría nueva no compila hasta que se le asigne ícono.

⚠ **`Lugar` y `LugarDestino` conviven.** Al construir 7.6 y 7.7 (lista y formulario de lugares) hay que
unificarlos en un solo modelo. Comparación (código y secciones 7.6 y 7.7):
- `LugarDestino` ya trae `nombre`, `lat` y `lng` con los mismos nombres que `Lugar(nombre, lat, lng)`, más `id`, `categoria` y `alias`: es un **superconjunto**, y obtener un `Lugar` desde un `LugarDestino` es copiar tres campos.
- 7.6 y 7.7 piden además descripción (texto que se lee al usuario), referencias cercanas y nº de fotos asociadas. `LugarDestino` **no tiene** ninguno. Sí cubre nombre, alias, categoría, coordenada e `imagenUrl`.
- La validación de 7.7 (nombre único, coordenada obligatoria) no está en el modelo: el modelo no valida nada.
- Sigue sin decidirse si se amplía `LugarDestino` con campos opcionales o se crea un modelo de edición aparte y `LugarDestino` queda como vista de lectura de 6.4.

**`ResumenAdmin`, `Usuario`, `AdminRepository` y `LugaresRepository` en detalle (verificado, bache 3)**

`ResumenAdmin` es una `data class` de 6 campos, sin valores por defecto, en este orden:

| Campo | Tipo | Notas |
|---|---|---|
| `totalFotos` | `Int` | |
| `totalLugares` | `Int` | |
| `alertasActivas` | `Int` | |
| `ultimoVideoNumero` | `Int?` | Número del último video recolectado (`video12` → 12); `null` si aún no hay videos |
| `ultimoVideoFecha` | `Long?` | Fecha y hora de ese video, en milisegundos epoch |
| `fotosPendientes` | `Int` | Fotos guardadas en el teléfono que aún no se han subido (cola local) |

- Son **6 campos pero 5 datos** en el panel: el último video usa número y fecha. Por eso 7.2 («Resumen rápido, con 5 datos») y 11.5 hablan de 5.
- ⚠ **Orígenes mezclados.** Según el KDoc de `AdminRepository`, totales, lugares y alertas activas salen del backend (`GET /admin/stats`) y las fotos pendientes, de la cola local (`data/local`), no del backend. El KDoc **no dice** de dónde sale el último video (¿backend o `VideoRepository`?). La implementación real tendrá que combinar dos orígenes en una sola llamada. Además, `ultimoVideoFecha` es `Long` en milisegundos, pero `Video.creadoEn` es texto del manifest (ver arriba): alguien tiene que convertirlo.

`AdminRepository`: `suspend fun obtenerResumen(): ResumenAdmin`; la `IOException` («si no hay conexión») solo está en el KDoc. `AdminRepositoryStub` espera 600 ms y devuelve 2842 fotos, 48 lugares, 3 alertas, video 12, `ultimoVideoFecha = System.currentTimeMillis()` y 27 fotos pendientes. Cuidados del stub: nunca lanza excepción, así que el estado de error del panel no se puede ver; la fecha es siempre «ahora», por lo que el panel muestra siempre «Hoy, HH:mm»; el último video nunca es nulo, así que no se ve el «—»; y dice 48 lugares mientras `LUGARES_DE_PRUEBA` tiene 6.

`Usuario.kt`: `enum class Rol { USER, ADMIN }`, `Usuario(id: String, nombre: String, correo: String, rol: Rol)` y `Sesion(token: String, usuario: Usuario)`. Las tres son sin valores por defecto, y las dos últimas son `data class`. El KDoc de `Sesion` dice que el token nunca se registra en logs. Coincide con 11.3: `SessionManager.obtener()` devuelve `""` si faltan id, nombre o correo.
- ⚠ **El `toString()` autogenerado de `Sesion` incluye el token y el de `Usuario`, el correo.** Interpolar una `Sesion` o un `Usuario` en un `AppLog` los escribiría en Logcat y en el archivo de logs, contra lo que dice el KDoc. Solución simple: sobrescribir `toString()` en ambas. No se buscó si algún código lo hace hoy.

`LugaresRepository`: `suspend fun obtenerLugares(): List<LugarDestino>`, «con su distancia a la posición actual» (`GET /places`); la `IOException` solo está en el KDoc. `LugaresRepositoryStub` espera 300 ms y devuelve `LUGARES_DE_PRUEBA`, un `val` público del mismo archivo (coordenadas aproximadas, solo mientras no exista backend). Los 6 lugares (ids únicos, apto para `key = { it.id }`):

| `id` | Nombre | Categoría | Alias | `distanciaMetros` |
|---|---|---|---|---|
| `biblioteca-central` | Biblioteca Central | `BIBLIOTECA` | biblioteca, la biblioteca | 85 |
| `cafeteria-principal` | Cafetería Principal | `CAFETERIA` | cafeteria, cafe, la cafeteria | 120 |
| `banos-bloque-a` | Baños Bloque A | `BANO` | banos, bano, los banos | 150 |
| `bloque-trillizos` | Bloque de los Trillizos | `BLOQUE` | trillizos, los trillizos | 200 |
| `auditorio-principal` | Auditorio Principal | `AUDITORIO` | auditorio | 260 |
| `entrada-principal` | Entrada Principal | `ENTRADA` | entrada, porteria | 310 |

Qué casos **no** ejercitan estos datos de prueba:
- Ningún lugar tiene `imagenUrl`: siempre se ve el ícono de la categoría.
- Todos tienen distancia (fija, creciente y en el mismo orden de la lista): no se ve el caso sin ubicación ni el ⚠ de «Lugares cercanos» sin distancias (11.5).
- No hay lugares de `DEPORTES` ni de `ADMINISTRACION`: esos filtros dan «No hay lugares con estos filtros».
- El stub nunca lanza `IOException`: el error de carga de Destino (`SIN_CONEXION`) no se puede ver.
- No existen «Bloque A» y «Bloque B»: el ⚠ 1 de `BuscarLugares` (11.7) no ocurre con estos nombres.

### 11.7 Casos de uso (lógica pura, sin Android)

| Pieza | Ubicación | Cómo se usa | Reglas |
|---|---|---|---|
| `BuscarLugares.mejores(consulta, lugares)` | `domain/usecase/BuscarLugares.kt` | Devuelve 0 (nada se parece), 1 (claro) o 2–3 lugares (empate: hay que pedir que elija). | **Verificado contra el código.** Normaliza (minúsculas, sin tildes, solo letras y números) y quita muletillas (lista fija: «quiero», «ir», «a», «al», «la», «el», «los», «las», «de», «del», «un», «una», «llevame», «llevarme», «lleves», «vamos», «hacia», «hasta», «para», «por», «favor», «me», «en», «donde», «esta», «necesito», «busco», «buscar»); si solo hay muletillas, las conserva. El puntaje de un lugar es el mejor entre su nombre y cada alias: si el texto limpio es **igual** al nombre o alias limpio → 1,0; si no, promedio sobre las palabras **dichas** de su mejor coincidencia en el candidato (igual 1,0; prefijo de 3 letras o más 0,9; parecida por Levenshtein con similitud ≥0,75 → ×0,9), y × 0,95 si el candidato es un nombre (los alias no se penalizan). Umbral 0,70; empate dentro de 0,04 del mejor; máximo 3 (los demás se descartan por orden de la lista). |
| `BuscarLugares.filtrar(lugares, texto)` | ídem | Filtro del buscador de una lista. | **Verificado.** Cada palabra escrita debe estar **contenida** (no solo al inicio) en alguna palabra del nombre, de un alias o de `categoria.etiqueta` (**singular**; no usa `etiquetaPlural`). Texto vacío → lista completa. No quita muletillas. |
| `InterpretarRespuesta.interpretar(texto)` | ídem | Devuelve `Respuesta.SI`, `NO` o `NINGUNA`. | **Verificado.** Compara **palabras completas** tras normalizar. Sí: «si», «claro», «correcto», «dale», «ok», «okay», «vale», «confirmo», «afirmativo», «exacto», «listo», «vamos», «adelante». No: «no», «nop», «nope», «cancela», «cancelar», «negativo», «incorrecto», «otro», «equivocado». Solo sí → `SI`; solo no → `NO`; ambas o ninguna → `NINGUNA` (p. ej. «está bien» o «de acuerdo» dan `NINGUNA`). `Respuesta` vive en el mismo archivo. Sirve para cualquier confirmación por voz. ⚠ `VoiceController.listen` entrega hasta 3 hipótesis **unidas en un solo texto**: si el reconocimiento duda entre "sí" y "no", el texto trae ambas y el resultado es `NINGUNA` (se debe volver a preguntar, no asumir). |
| `CalibracionPaso` | `domain/usecase/CalibracionPaso.kt` (`object`) | `calcular(distanciaM, pasos, duracionS): ResultadoCalibracion` y `distanciaEntre(lat1, lng1, lat2, lng2)` (haversine, R = 6 371 000 m; igual que `map.distance` de Leaflet). Constantes `MIN_PASO_M` 0,40 · `MAX_PASO_M` 1,20 · `MIN_PASOS` 15 · `MIN_DISTANCIA_M` 10 · `DISTANCIA_RECOMENDADA_M` 30. | **Verificado con kotlinc 2.0.21** (13 comprobaciones). `ResultadoCalibracion`: `Valido(longitudPasoM, pasos, distanciaM, duracionS, cadenciaPpm, velocidadMps)` o `Invalido(motivo, longitudPasoM?)`; `MotivoInvalido`: `TRAMO_CORTO`, `POCOS_PASOS`, `PASO_MUY_CORTO`, `PASO_MUY_LARGO` (orden de comprobación: tramo → pasos → rango). Con `duracionS = 0`, cadencia y velocidad valen 0. Los umbrales de 10 m y 15 pasos son elección propia. Test JUnit4 `CalibracionPasoTest` (**no ejecutado en Gradle**) |
| `DisparadorCaptura` y `ModoCaptura` | `domain/usecase/DisparadorCaptura.kt` | Decide cuándo tomar la siguiente foto de la recolección (cada N metros o N segundos). Ver 11.2, «Flujo de captura de la recolección». | Sin estado de Android: se puede probar con pruebas unitarias (todavía no hay). Llamar a `alCapturar` **solo si la foto se guardó** |
| `Deriva.estimar(distanciaDesdeAnclaM)` | ídem | `EstimacionDeriva(derivaM, precisionM, nivel)` con `NivelCalidad` `ALTA` (< 15 m), `MEDIA` (< 30 m) o `BAJA`. | Heurística **provisional**: 4 % de la distancia desde el último ancla (decisión 16) |

Se pueden probar sin emulador (solo Kotlin).

Uso verificado en `SeleccionDestinoViewModel` (11.5): `BuscarLugares.mejores(texto, todos)` → `List<LugarDestino>`, `BuscarLugares.filtrar(todos, busqueda)` e `InterpretarRespuesta.interpretar(texto)` → `Respuesta.SI / NO / NINGUNA`; las firmas coinciden con la tabla. Las **reglas** de la tabla se verificaron contra `BuscarLugares.kt` (bache 1). Dos matices del uso: `mejores` siempre busca en la lista **completa** (ignora la búsqueda y la categoría activas), y el «Di cuál quieres» tras ofrecer opciones vuelve a buscar sobre todos los lugares, no solo sobre las opciones ofrecidas.

**Comportamientos a tener en cuenta en `BuscarLugares`** (leídos en el código y probados con una copia de la lógica en Python; no se ejecutó el Kotlin, y los ejemplos usan nombres de muestra, no los lugares reales del stub):

1. ⚠ **Una coincidencia exacta gana sin preguntar.** Un nombre o alias idéntico al texto puntúa 1,0, mientras que un nombre parcial llega como máximo a 0,95: la diferencia (0,05) supera el margen de empate (0,04), así que un parcial nunca se ofrece junto a un exacto. Agravante: las muletillas también se quitan de los **nombres**, y «a» es muletilla, así que «Bloque A» se evalúa como «bloque». Con «Bloque A» y «Bloque B», decir «bloque» devolvió solo «Bloque A», sin pedir elegir. Con los 6 lugares reales del stub (bache 3) **no ocurre**: no existen «Bloque A» y «Bloque B», y decir «bloque» devuelve dos opciones («Baños Bloque A» y «Bloque de los Trillizos») y se pide elegir. Sigue latente si el backend trae nombres como «Bloque A» y «Bloque B».
2. ⚠ **Las hipótesis unidas de `listen` pueden anular una coincidencia.** El promedio cuenta todas las palabras del texto, sin quitar repetidas. Con «cafeteria cafe teria» no devolvió ningún lugar, mientras que «cafeteria» sola da 1,0. Se repite con los alias reales del stub (bache 3). Falta confirmar en `VoiceController` cómo se unen las hipótesis y si el ViewModel pasa ese texto tal cual. Opciones: puntuar cada hipótesis por separado y quedarse con la mejor, o quitar palabras repetidas.
3. **El umbral efectivo de la coincidencia difusa es mayor que 0,75.** Para llegar a 0,70 con una sola palabra parecida hace falta una similitud de ≈0,82 contra un nombre y ≈0,78 contra un alias. Una palabra de 5 letras con un error no basta contra un nombre, pero sí contra un alias: los alias ayudan más de lo que parece.
4. **El prefijo es asimétrico:** solo cuenta que la palabra **dicha** sea prefijo de la del lugar («cafe» → «cafeteria»), nunca al revés, y exige 3 letras o más.
5. **El comentario del código no coincide con la lógica:** dice «un nombre parcial vale menos que un alias exacto», pero la penalización de 0,95 se aplica a todo nombre que no sea idéntico; un alias parcial no se penaliza.
6. **`filtrar` es una búsqueda por «contiene»:** «a» deja pasar casi todos los lugares. Usa `categoria.etiqueta` (singular): escribir «entradas» no coincide con la categoría «Entrada» aunque el chip diga «Entradas». La `ñ` se normaliza («baño» = «bano»).
7. **Sin estado ni Android:** `BuscarLugares` e `InterpretarRespuesta` son `object` sin estado y solo importan `LugarDestino` y `java.text.Normalizer`; se pueden llamar desde cualquier hilo y probar con pruebas unitarias. `limpiar` es `internal` y la usa `InterpretarRespuesta`.
8. **Un empate de 3 ya llena el máximo.** Con el stub, «principal» devuelve Cafetería, Auditorio y Entrada Principal (0,95 cada una): si el backend trae un cuarto lugar «… Principal», quedaría fuera sin aviso, por el orden de la lista.

### 11.8 Rutas y datos que viajan entre vistas

| Ruta | Pantalla | Recibe | Entrega (callbacks) |
|---|---|---|---|
| `inicio` | `InicioScreen` | — | `onUbicarme` → `ubicarme`, `onIrALugar` → `destino`, `onAccesoAdministrador` → `login` |
| `ubicarme` | `EscaneoScreen` | — | `onCompletado` (**sin datos**; hoy hace `popBackStack()`, TODO resultado 6.3), `onCancelar` → `popBackStack()`. `onAjustes` **no está conectado** (valor por defecto `{}`) |
| `destino` | `SeleccionDestinoScreen` | — | `onDestinoConfirmado(LugarDestino)` (hoy **descarta** el destino y abre `ubicarme`), `onAjustes` → `ajustes`, `onVolver` |
| `login` | `LoginScreen` | — | `onLoginExitoso` → `admin/panel` (quita `login` de la pila), `onVolver` |
| `admin/panel` | `PanelAdminScreen` | — | `onRecolector` → `admin/ubicacion-manual`, `onLugares` → `admin/lugares`, `onMapaAlertas` → `admin/mapa`, `onImagenes` → `admin/imagenes`, `onVideos` → `admin/videos`, `onEstadisticas` → `admin/estadisticas`, `onAjustes` → `ajustes`; `onVolverModoPublico` y `onSesionCerrada` → vuelven a `inicio`; `onSinSesion` → `login` (quita el panel de la pila) |
| `admin/ubicacion-manual` | `UbicacionManualScreen` (7.3) | — | `onVolver` (flecha y «Cancelar») → `popBackStack()`, `onAjustes` → `ajustes`, `onCalibrar` → `navigate("admin/calibracion")`, `onConfirmar(InicioRecoleccion)` → `SesionDeRecoleccion.iniciar(inicio)` y `navigate("admin/recoleccion")` (7.3 queda en la pila: su ViewModel reactiva «Confirmar» con `alReanudar()`). Pide `Permisos.INICIALES` antes de mostrar la pantalla y descarta el resultado |
| `admin/calibracion` | `CalibracionScreen` (7.3b) | — | Pide `Permisos.ACTIVIDAD` antes de mostrar la pantalla y **descarta el resultado** (si se niega, el PDR usa el acelerómetro y la pantalla lo avisa; antes de Android 10 la lista está vacía y pasa directo). `onVolver` → `popBackStack()`. Se llega desde la fila «Calibrar mi paso» de 7.3. No devuelve datos: el resultado se guarda en `CalibracionPasoRepository` (11.6) y lo recoge cada `PdrTracker` al crearse |
| `admin/recoleccion` | `RecoleccionScreen` (7.4) | `InicioRecoleccion` por `SesionDeRecoleccion` (no por la ruta) | Pide **solo la cámara** antes de mostrar la pantalla (como `ubicarme`; si se niega, `popBackStack()`). `onFinalizado(resumen)` → `SesionDeRecoleccion.finalizar(resumen)` y `navigate("admin/recoleccion/resumen") { popUpTo("admin/ubicacion-manual") { inclusive = true } }` (saca 7.3 y 7.4 de la pila); `onDescartado` (video sin fotos) → `popBackStack("admin/panel", inclusive = false)`; `onVolver` (solo con error, p. ej. `SIN_INICIO`) → `popBackStack()`; `onAjustes` → `ajustes` |
| `admin/recoleccion/resumen` | Placeholder (7.5, falta `ResumenVideoScreen`) | `SesionDeRecoleccion.resumen` | Pantalla en blanco: solo se sale con Atrás |
| `admin/mapa` | `EditorMapaScreen` | `posicionAdmin: () -> Pair<Double, Double>?` (hoy `{ null }`) | `onVolver`, `onVerLista` (hoy vacío; el comentario dice «vista 17», que corresponde a la lista de alertas 7.10) |
| `admin/imagenes` | `GaleriaScreen` | — | `onVolver`, `onAbrirImagen(videoId, fotoId)` (placeholder, falta 7.12) |
| `admin/videos` | `VideosScreen` | — | `onVolver`, `onAbrirVideo(id)` → `admin/videos/<id>` |
| `admin/videos/{videoId}` | `VideoDetalleScreen` | `videoId` (argumento de ruta, texto) | `onVolver`, `onAbrirImagen(videoId, fotoId)` (placeholder, falta 7.12) |

Rutas con placeholder vacío (pantalla en blanco, no cierran la app): `admin/recoleccion/resumen`, `admin/lugares`,
`admin/estadisticas`, `ajustes`. Registrar una ruta **dos veces** hace que la última
reemplace a la primera (un placeholder puede tapar la pantalla real); navegar a una ruta **no
registrada** cierra la app con un error.

**Verificado en `MainActivity.kt` (`AppNav`):**
- **El `NavHost` vive en `MainActivity.kt`**, no en `ui/navigation/AppNavHost.kt` (sección 4). Ruta
  inicial: `inicio`. Cada pantalla crea su propio ViewModel; `AppNav` **no** crea ni comparte ninguno.
- **Único dato que viaja por ruta:** `videoId`, como argumento de texto sin `navArgument` declarado y sin
  codificar. El id del video es el nombre de su carpeta (11.6): no usar `/` ni caracteres especiales.
  Si el argumento falta, la ruta no dibuja nada.
- **La recolección no usa argumentos de ruta:** los datos viajan por `SesionDeRecoleccion` (11.6; decisión 15).
- **Sin protección de rutas `admin/*`:** `AppNav` no comprueba la sesión al entrar en `admin/mapa`,
  `admin/imagenes` ni `admin/videos[/{id}]`; solo el panel dispara `onSinSesion`. ⚠ Confirmar si cada
  pantalla admin lo comprueba por su cuenta. Ojo con la restauración tras matar el proceso: `MyApp`
  ya habrá borrado la sesión (11.3) y Android puede restaurar la pila en una pantalla admin.
- **Permisos en la ruta:** `inicio` pide los iniciales y `ubicarme` la cámara antes de mostrar la
  pantalla (ver 11.3). `admin/recoleccion` pide solo la cámara; la ruta de navegación (6.5) deberá hacer lo mismo. `admin/calibracion` pide solo `Permisos.ACTIVIDAD`.
  `admin/ubicacion-manual` ya pide `Permisos.INICIALES` y descarta el resultado (la 7.3 en sí no necesita
  ninguno: la brújula usa el sensor de rotación; el de actividad física lo usa la 7.4 para el PDR (se pide en la ruta de 7.3), que
  sin él usa el acelerómetro, 11.2).
- **`inicio` (verificado en el código):** `PedirPermisos` va **antes** de `InicioScreen` y su resultado se ignora (`permisosPedidos = true` sea cual sea); mientras tanto no se dibuja nada. Por eso la explicación hablada de `InicioScreen` nunca suena antes del primer diálogo (11.5, Inicio).
- **`destino` → `ubicarme`:** `onDestinoConfirmado` hace `nav.navigate("ubicarme")` **sin quitar** `destino` de la pila (queda `[inicio, destino, ubicarme]`). Al terminar el escaneo, `popBackStack()` vuelve a Destino con su ViewModel intacto (11.5).
- **Bordes del sistema:** `MainActivity` llama a `enableEdgeToEdge()`, así que cada pantalla debe aplicar `statusBarsPadding` / `navigationBarsPadding` (o `systemBarsPadding`) y, con teclado, `imePadding`. Inicio, Destino y Login ya lo hacen.

⚠ **Brecha en el flujo público** (la recolección ya la resolvió con `SesionDeRecoleccion`): hoy **no hay dónde guardar datos compartidos entre vistas públicas** (el destino elegido, la
posición estimada, si hay una ubicación vigente). Hay que resolverlo antes de 6.3 y 6.5 (ver decisión
abierta 15). Dos puntos concretos donde se pierde información hoy: `onDestinoConfirmado` descarta el
`LugarDestino`, y el `EscaneoEvento.Completado` no lleva resultado (`backend.analizar` devuelve `Unit`; ver "Flujo de captura del escaneo" en 11.2).

Verificado en los ViewModels: `DestinoEvento.Confirmado` **sí** lleva el `LugarDestino` completo (se pierde después, en `AppNav`); `InicioEvento` y `LoginEvento.IrAlPanel` no llevan datos. Además, `SeleccionDestinoViewModel` conserva `candidato` tras confirmar y `destino` sigue en la pila (ver arriba): al volver del escaneo, la confirmación queda pendiente (11.5).

### 11.9 Puentes WebView ↔ Android

Cada mapa es una página en `assets/` (HTML + JS con Leaflet) con su puente Kotlin: `AndroidBridge`
(mapa público, 2.6), `EditorBridge` (7.8), `VideoBridge` (7.14), `UbicacionBridge` (7.3), `RecoleccionBridge` (7.4) y `CalibracionBridge` (7.3b); los tres últimos, en 11.5. Los datos viajan como JSON; las
tablas de funciones están en esas secciones. Funciones y cuidados del `EditorBridge` y de `VideoBridge` en 11.5.
`env(safe-area-inset-*)` no funciona en `WebView`, así que la app pasa el alto de las barras en dp con
`setInsets(top, bottom)` (el mapa público no lo usa: su pantalla aplica `systemBarsPadding()`).

> ⚠ **Código entregado el 2026-10-10.** El lado web se probó con jsdom (27 comprobaciones, incluido el caso
> «Leaflet no carga»); el lado Kotlin **no se compiló** ni se probó en dispositivo. Confirmar y quitar este aviso.

**Infraestructura común (dos piezas):**

| Pieza | Ubicación | Qué hace |
|---|---|---|
| `MapaBase` (JS) | `assets/mapa_base.js` | Se carga **después de Leaflet y antes** del script de la página. No hace nada al cargarse. |
| `MapaWebView` (Kotlin) | `map/MapaWebView.kt` | Una sola fábrica del `WebView` para todas las pantallas de mapa. |

**`MapaBase` (JS)** — `window.MapaBase`:
- `iniciar({ puente })` → `{ existe(), call(fn, ...args), leaflet }`. Se llama **primero**, antes de comprobar Leaflet, y deja
  listo lo que Kotlin necesita aunque el mapa no cargue: `window.setInsets`, un `window.onAtras` por defecto (llama a
  `salir()`), el botón `#btn-back`, las medidas (`--toph` / `--dockh` con `ResizeObserver`; usa los ids `top` y `dock`) y,
  si no hay Leaflet, el aviso «No se pudo cargar el mapa…». La página termina con `if (!base.leaflet) return;` y después
  reemplaza `window.onAtras` por el suyo. `call` devuelve `true` si había puente; si no, la página usa datos de demo.
- ⚠ **`crearMapa` no es parte del objeto que devuelve `iniciar`:** se llama `MapaBase.crearMapa(...)`. Solo `base.existe`, `base.call` y `base.leaflet` cuelgan de `base`; `toast`, `dialogo`, `confirmar`, `medir`, `$`, `ic`, `esc` y `puente` también son de `MapaBase`. Escribir `base.crearMapa(...)` lanza `TypeError` y deja el mapa **negro y sin aviso** (pasó en `calibracion_mapa.js`, corregido el 2026-10-12). ⚠ **Revisar que `recoleccion_mapa.js` use `MapaBase.crearMapa`** (se escribió con el mismo supuesto).
- `crearMapa({ centro, zoom, maxZoom })` → mapa Leaflet con las teselas de OSM (nativas hasta el zoom 19; `maxZoom` mayor las
  amplía: el detalle de video usa 21), atribución «© OSM» y control de zoom, ambos abajo a la izquierda.
- `toast`, `dialogo({ texto, label, peligro, input, valor, placeholder, valida, ok })`, `confirmar(texto, ok, label = 'Eliminar')`,
  `medir`, `$`, `ic`, `esc` y `puente(nombre)`.
- `app.js` (mapa público) **solo** usa `MapaBase.puente('AndroidBridge').call` en lugar de su antiguo `bridgeCall`: no tiene
  `dialogo`, `medir` ni `setInsets`, y su `toast` es otro (`#toast-container`). Por eso carga `mapa_base.js` pero no llama a `iniciar`.

**`MapaWebView` (Kotlin)** — paquete `map`:

| Pieza | Firma | Qué hace / cuidado |
|---|---|---|
| `MapaWeb` / `rememberMapaWeb()` | `class MapaWeb` · `listo: Boolean` (estado) · `js(codigo)` | Controlador de una pantalla: `listo` pasa a `true` cuando la página llama a `listo()`; `js` ejecuta JavaScript (hilo principal). Usar `LaunchedEffect(mapa.listo, dato)` para empujar estado. |
| `literalJs(s)` | `(String) -> String` | Texto → literal de JavaScript (`JSONObject.quote`), para `cargarX(${literalJs(json)})`. |
| `PuenteWeb(mapa)` | `open class` · `listo()` · `enHiloPrincipal { }` | Base de los puentes: ya trae `listo()`. Cada subclase añade sus `@JavascriptInterface` y los pasa por `enHiloPrincipal` (llegan en un hilo del `WebView`). **Debe ser pública o `internal`, nunca `private`** (el `WebView` la invoca por reflexión). |
| `MapaWebView` | `(mapa, html, puente, nombrePuente, tag, modifier = fillMaxSize(), pasarInsets = true, manejarAtras = true)` | Crea el `WebView` (tamaño, fondo `#0A0E1A`, JS, DOM storage, depuración solo en builds depurables, consola y errores a Logcat con `tag`), registra el puente, carga `file:///android_asset/<html>`, envía `setInsets` y conecta el `BackHandler` con `window.onAtras()`. `pasarInsets = false` si la página no define `setInsets`. `onRelease` destruye el `WebView`. |

Receta para una pantalla de mapa nueva (como `EditorMapaContent` y `VideoDetalleContent`):

```kotlin
val mapa = rememberMapaWeb()
val eventosActuales by rememberUpdatedState(eventos)
val puente = remember(mapa) { MiPuente(mapa) { eventosActuales } }   // internal class MiPuente(...) : PuenteWeb(mapa)
MapaWebView(mapa, html = "mi_mapa.html", puente = puente, nombrePuente = "MiBridge", tag = "MiMapa")
LaunchedEffect(mapa.listo, json) { if (mapa.listo) mapa.js("cargarX(${literalJs(json)})") }
```
Y en la página: `<script>` de Leaflet, `mapa_base.js`, el JS de la página; en este, `const base = MapaBase.iniciar({ puente: 'MiBridge' }); if (!base.leaflet) return;`.

Cuidados:
- **Falta migrar `MapaPublicoScreen`** (⚠ su código no se revisó en este cambio): sigue con su propia fábrica de `WebView`.
  `MapaWebView` acepta cualquier objeto como `puente` (sirve `PuentePdr`) y `pasarInsets = false`, y el modificador
  `Modifier.systemBarsPadding()`; los `window.onNative*` se siguen enviando con `evaluateJavascript` desde esa pantalla.
- Los datos del usuario o del repositorio siempre con `textContent` o `esc()`, nunca interpolados en `innerHTML` (excepción: `bindTooltip` del editor).
- Las tres páginas (`index.html`, `editor_mapa.html`, `video_detalle.html`) siguen cargando Leaflet 1.9.4 desde `unpkg.com`
  sin `integrity` y las fuentes de Google Fonts, y llevan `user-scalable=no` en el `viewport` (decisión abierta 13).
- Un `onAtras` por defecto que llama a `salir()` evita el defecto anterior (sin Leaflet, Atrás y Volver no hacían nada).
  Aun así, sin Leaflet la página nunca llama a `listo()` y la app no le envía datos.
- `RecoleccionBridge` (7.4) es una página **embebida** en una tarjeta de Compose: usa `MapaBase.iniciar` y `crearMapa`, pero con `pasarInsets = false` y `manejarAtras = false` (Atrás lo maneja la pantalla); lleva ocultos `#top`, `#dock` y `#btn-back` por si `MapaBase.iniciar` no tolera que falten (11.5).
- `CalibracionBridge` (7.3b) es igual de embebido que `RecoleccionBridge` (`pasarInsets = false`, `manejarAtras = false`, mismos elementos ocultos); marca A y B con toques y pines arrastrables y usa el zoom nativo de Leaflet (11.5).

### 11.10 Lo que aún no está documentado aquí (⚠)

Se completa la primera vez que alguien los necesite: al leer el archivo, agregar su entrada.

**Ya documentado y verificado contra el código:** `VoiceController` y `ComandoParser` (11.2; viven
en el mismo archivo), `SessionManager` (11.3), `VideoRepository`/`AssetsVideoRepository`/
`EdicionesLocales` y `Foto.kt` (11.6), `AuthRepository` y `Alerta.kt` (11.6), `OrientationProvider` y
`CapturaFoto` (sensores y cámara, antes de 11.3), `ui/ubicacion/componentes/` (11.5), `MyApp.kt`
(11.2 y 11.3), `MainActivity.kt` (`Permisos`, `PedirPermisos`, `AppNav`; 11.3 y 11.8),
`EscaneoViewModel.kt` (flujo de captura, antes de 11.3), `FeedbackCaptura.kt` y `AppLog.kt` (11.2) y
`AlertaFormSheet.kt` (11.5), `EscaneoState.kt`, `EscaneoConfig.kt` (con `EscaneoColores`),
`EscaneoBackend.kt` y `EscaneoScreen.kt` (flujo de captura, antes de 11.3; equivalencias de color en
11.4) `EditorMapaViewModel.kt`, `EditorMapaScreen.kt`, `editor_mapa.html` y `editor_mapa.js` (con `EditorBridge`), `PanelAdminViewModel.kt` y `PanelAdminScreen.kt`, `GaleriaViewModel.kt` y `GaleriaScreen.kt` (con `GaleriaColores`), `VideosScreen.kt`, `VideoDetalleViewModel.kt` y `VideoDetalleScreen.kt`, `video_detalle.html` y `video_detalle.js` (con `VideoBridge`) (11.5), y `CampusColors.kt` (11.4). **Tanda 12 (2026-10-12, vista 7.3b y cambios en 7.3):** archivos **nuevos** `CalibracionPaso.kt`, `CalibracionPasoRepository.kt`, `CalibracionState.kt`, `CalibracionViewModel.kt`, `CalibracionScreen.kt`, `componentes/MapaCalibracion.kt` (con `CalibracionPuente`), `calibracion_mapa.html`, `calibracion_mapa.js` y `CalibracionPasoTest.kt`; **parches** a `PdrEngine.kt` y `PdrTracker.kt` (longitud de paso inyectable); y, **releídos en esta tanda**, `MainActivity.kt` (`Permisos.ACTIVIDAD`, ruta `admin/calibracion`, `onCalibrar`) y `UbicacionManualScreen.kt` (fila «Calibrar mi paso», `onCalibrar`, `longitudCalibradaM`) (7.3, 7.3b, 11.2, 11.3, 11.5 a 11.9; el proyecto compila con ellos y la pantalla se abre en dispositivo; ⚠ la pasada completa de calibración sigue sin probar). **Tras compilar el proyecto entero, el aviso «Kotlin sin compilar» de las tandas anteriores ya no aplica a lo que forma parte del build** (cada entrada con ⚠ sigue pendiente de prueba **en dispositivo**). **Tanda 11 (2026-10-11, vista 7.4):** archivos **nuevos** `FotoRecolectada.kt`, `SesionRecoleccion.kt`, `DisparadorCaptura.kt`, `RecoleccionRepository.kt`, `RecoleccionState.kt`, `RecoleccionViewModel.kt`, `RecoleccionScreen.kt`, `componentes/PanelesRecoleccion.kt`, `componentes/MapaRecoleccion.kt` (con `RecoleccionPuente`), `recoleccion_mapa.html` y `recoleccion_mapa.js`, y los cambios de `AppNav` en `MainActivity.kt` (7.4, 11.2, 11.5, 11.6, 11.7, 11.8 y 11.9; compilan y funcionan según quien los escribió; ⚠ documentados a partir de lo entregado, **sin releerlos contra el código final**: si se retocaron al compilar, confirmar firmas y nombres). **Tanda 10 (2026-10-11):** archivos **nuevos** `UbicacionManualScreen.kt`, `UbicacionManualViewModel.kt`, `UbicacionManualState.kt`, `InicioRecoleccion.kt`, `ubicacion_manual.html` y `ubicacion_manual.js` (11.5, 11.6, 11.8 y 11.9; ⚠ Kotlin sin compilar, escritos sin ver `MainActivity.kt`, `MapaWebView.kt` ni `mapa_base.js`: los supuestos están en 11.5). **Tanda 9 (bache 4):** `app.js` e `index.html` (estructura e ids), `OrientationProvider.kt` y `MainActivity.kt` (releídos), y los archivos nuevos `PdrEngine.kt`, `StepDetector.kt`, `PdrTracker.kt`, `PuentePdr.kt` y `MapaPublicoScreen.kt` (2.3, 2.6, 11.2, 11.5, 11.8 y 11.9; ⚠ los nuevos sin probar en dispositivo). **Tanda 8 (bache 3):** `LugaresRepository.kt` (con `LUGARES_DE_PRUEBA`), `AdminRepository.kt`, `ResumenAdmin.kt` y `Usuario.kt` (con `Rol` y `Sesion`) (11.5, 11.6 y 11.7). **Tanda 7 (bache 2):** `PanelesVoz.kt`, `ListaLugares.kt` y `Comun.kt` de `ui/destino/componentes/` (11.5 y 11.6). **Tanda 6 (bache 1):** `BuscarLugares.kt` (con `InterpretarRespuesta` y `Respuesta`), `LugarDestino.kt` (con `CategoriaLugar`) y `SeleccionDestinoState.kt` completo (`OrdenLugares`, `ErrorDestino`, `DestinoEvento`) (11.5, 11.6 y 11.7). **Tanda 5:** `MainActivity.kt` (releído: confirma 11.3 y 11.8 y añade notas), `SeleccionDestinoScreen.kt`, `DestinoUiState` (de `SeleccionDestinoState.kt`, pegado por la persona) y `LoginScreen.kt` (11.5). **Tanda 4:** `VideosViewModel.kt`, `LoginViewModel.kt`, `InicioViewModel.kt` (con `BackendHealth`), `InicioScreen.kt` y `SeleccionDestinoViewModel.kt` (11.5; ajustes en 11.1, 11.2, 11.3, 11.4, 11.6 a 11.8).

**Pendiente:**
- Vista 7.3 (`UbicacionManualScreen`): **probarla en dispositivo**; confirmar los supuestos de 11.5; decidir el nombre `video_N` frente a `video3` de este documento; fijar `CampusMapa.CENTRO`; decidir si se hace la foto de referencia del diseño; mover `BotonIcono` y `Modifier.tarjeta` a `ui/components/`; **retirar `MapaPublicoScreen` de la ruta** (queda como referencia del PDR) y quitar el botón GPS que ya no se usa en esa vista.
- Vista 7.3b (`CalibracionScreen`): **probar la pasada completa en dispositivo** (A→B, guardar, recolectar con la longitud calibrada); **ejecutar `CalibracionPasoTest`** en Gradle; confirmar si el valor genérico debe ser 0,70 m (el encargo) o 0,72 m (el código); sustituir el centro aproximado del mapa por `CampusMapa.CENTRO`; revisar `recoleccion_mapa.js` por el mismo error `base.crearMapa` (11.9); mover `BotonIcono` y `Modifier.tarjeta` a `ui/components/`.
- Vista 7.4 (`RecoleccionScreen`): ver «Pendiente / fuera de alcance» en 7.4. Además: **`ResumenVideoScreen` (7.5)**, un `VideoRepository` compuesto con parser de manifest compartido (11.6), `AlertasRepository` (alertas existentes y persistencia de las nuevas), «Marcar punto de interés» (7.6 y 7.7), control de calidad de imagen, retomar tras matar el proceso, y pruebas unitarias de `DisparadorCaptura` y `Deriva`.
- `ui/admin/`: `mapa/AlertasScreen.kt` (7.10) y la vista 7.12 **todavía no existen**.
- Mapa público y PDR (bache 4, hecho): `app.js`, `index.html`, `PuentePdr.kt` y `MapaPublicoScreen.kt` ya
  documentados. Falta **probarlos en dispositivo** y quitar los ⚠ de 2.6, 10 y 11.2.
- PDR: la longitud de paso ya es calibrable (7.3b, decisión 16 resuelta); falta calibrar la deriva de la brújula (la deriva de 7.4 usa una heurística provisional que
  habrá que reemplazar), navegación (6.5) sobre `PdrTracker`, manejo de `ON_STOP` en `PdrTracker` (hoy lo resuelve
  el ViewModel de la recolección) y corrección visual con fusión (`domain/fusion/`).
- `MapaPublicoScreen` (`map/`) **sigue con su propia fábrica de `WebView`**: migrarla a `MapaWebView(…, pasarInsets = false)` (11.9) y comprobar que `PuentePdr` y los `evaluateJavascript` de `onNative*` siguen funcionando. Además, el CSS de las páginas (`.toast`, `.modal`, estilos de los controles de Leaflet, `.ic`) sigue duplicado entre `editor_mapa.html` y `video_detalle.html`: candidato a `mapa_base.css`.
- Decidir el nombre del producto («Campus Locator» en este documento, «Campus Navi» en `LoginScreen`).
- Decidir qué hace el orbe de Inicio y si vuelven los dos botones, el micrófono y Ajustes de 6.1 (ver Inicio en 11.5).
- `domain/usecase/`: las reglas de 11.7 ya están verificadas (bache 1). La sección 4 solo lista `BuscarLugares.kt` ahí; si existen más casos de uso, no se han visto.
- Decidir cómo resolver los dos ⚠ de `BuscarLugares` (11.7: coincidencia exacta que gana sin preguntar e hipótesis unidas de `listen`) y qué campos suma la unificación de `Lugar` y `LugarDestino` (11.6).
- Decidir qué hacer con los ⚠ de `ui/destino/componentes/` (11.5): chip «Más» sin nombre para TalkBack, posible solapamiento de voces (tres `liveRegion` + `VoiceController`; comprobar en dispositivo), «Lugares cercanos» sin distancias, miniatura sin ícono de respaldo y qué hace `alPresionarMicrofono` al tocar mientras escucha.
- Decidir los ⚠ de 11.6 sobre repositorios y modelos: `toString()` de `Sesion` con el token, origen del último video en `ResumenAdmin` y conversión de `creadoEn` (texto) a milisegundos, y enriquecer los stubs (errores `IOException`, lugares de `DEPORTES` y `ADMINISTRACION`, `imagenUrl`, distancias nulas, fecha y último video nulos).
- Revisar si las pantallas admin comprueban la sesión por su cuenta (ver 11.8).