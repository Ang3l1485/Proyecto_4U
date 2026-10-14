# Campus Locator

Aplicación Android (Kotlin + Jetpack Compose) que **ubica y guía por voz a personas con
discapacidad visual dentro de un campus universitario**, usando la cámara, los sensores
de movimiento del teléfono y un servicio backend que compara imágenes mediante embeddings
(DINOv2).

Es **una sola app y un solo APK** con dos flujos:

1. **Flujo público (usuario final):** ubicarse en el campus o ser guiado hacia un lugar,
   todo controlado por voz y con soporte de lector de pantalla.
2. **Flujo protegido (recolector / admin):** tras iniciar sesión con una cuenta con rol de
   administrador se habilita el panel de recolección, donde se construye el dataset de
   imágenes + embeddings + coordenadas que hace posible el flujo público.

---

## ¿Qué hace la app?

### 1. "¿Dónde estoy?" (ubicarse)

1. El usuario dice **"uno"** (o toca el botón grande de la pantalla de inicio).
2. La app le indica por voz que sostenga el celular al frente y **dé una vuelta completa
   (360°) lentamente**.
3. El usuario **no toma fotos manualmente**: la app captura automáticamente **5 fotos**
   repartidas a lo largo de la vuelta (aprox. cada 72°, usando el sensor de orientación)
   y las envía al backend.
4. El backend calcula embeddings con DINOv2, los compara contra el dataset y devuelve la
   posición estimada.
5. La app comunica por voz dónde está el usuario (ej. *"Estás cerca de la biblioteca,
   mirando hacia el bloque de los trillizos"*) y lo muestra en el mapa.

### 2. "Quiero ir a…" (navegación guiada)

1. El usuario dice **"dos"** y luego **el nombre del lugar** al que quiere ir.
2. Primero se **ubica** al usuario con el mismo proceso del punto anterior.
3. Se calcula la ruta y la app lo guía **por voz** paso a paso: seguir recto, girar a la
   izquierda/derecha, distancia restante, llegada, etc. También **avisa de obstáculos
   cercanos** (lagos, bancas, escaleras, obras…) mediante **alertas puestas en el mapa por
   el admin**: cuando el usuario se acerca a una, la app le lee el mensaje escrito por el
   recolector (ej. *"Ten cuidado, hay un lago alrededor de la biblioteca"*).
4. Mientras camina, la posición se mantiene con **dos sistemas combinados**:
   - **Navegación inercial (PDR):** pasos, velocidad, aceleración y orientación van
     actualizando la posición en el mapa en tiempo real.
   - **Corrección visual automática:** cada cierto tiempo, y sin intervención del usuario,
     la app captura una foto, la envía al backend y recibe una posición que **corrige el
     error acumulado** del sistema inercial.

### 3. Recolección del dataset (admin / recolector)

El dataset es la base de todo: **cada foto de referencia = embedding DINOv2 + coordenada
(+ orientación)**. Alguien debe construirlo antes de que el flujo público funcione; esa
persona es el **recolector**, que será el propio administrador de la universidad:

1. Inicia sesión como admin.
2. **Se ubica manualmente en el mapa** para fijar su coordenada exacta de partida.
3. Camina por el campus (cada recorrido es un **"video"**: no se guarda el video, solo
   agrupa las fotos de ese recorrido); el sistema usa **pasos, velocidad, aceleración y orientación**
   para ir actualizando su coordenada, y **captura fotos automáticamente** guardándolas
   junto con su coordenada estimada.
4. Al finalizar el video, las fotos se suben al backend, que genera los embeddings y los
   indexa para búsqueda por similitud.
5. El admin puede **seleccionar un video (ej. "video1") y ver en el mapa SOLO sus fotos**, y
   también **eliminarlo**: se borran el video y todas sus fotos y embeddings del dataset.
6. El admin también **edita el mapa (`eafit.mbtiles`) colocando alertas de obstáculo**: un
   punto en el mapa + un mensaje de texto libre que el sistema le leerá al usuario ciego
   cuando esté cerca (ej. *"Ten cuidado, hay bancas cerca, no te vayas a estrellar"*).
   Puede crearlas desde el editor de mapa o directamente mientras camina recolectando fotos.
7. El admin además gestiona lugares/destinos, revisa la galería, y consulta estadísticas.

---

## Resumen de pantallas

| Flujo | Pantallas |
|---|---|
| Público | Inicio, Ubicarse (escaneo 360°), Resultado de ubicación, Selección de destino, Navegación guiada, Llegada, Ajustes |
| Admin | Login, Panel admin, Ubicación manual inicial, Recolección en curso, Resumen de video, Lugares, Editor de mapa y alertas, Lista de alertas, Galería de imágenes, Detalle de imagen, Lista de videos, Detalle de video, Estadísticas |

El detalle de cada pantalla (elementos, botones, comportamiento y archivo asociado) está
en [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Tecnologías

- Kotlin + Jetpack Compose
- CameraX (captura de frames)
- Sensores: acelerómetro, giroscopio, magnetómetro / rotation vector, step detector
- Text-to-Speech y Speech Recognizer de Android (interacción por voz) + TalkBack
- Mapa del campus: `eafit.mbtiles` (MBTiles) con capa propia de alertas de obstáculos
- Backend propio: DINOv2 (embeddings) + búsqueda por similitud vectorial
- Autenticación con roles (usuario público / admin)

## Requisitos

- Android Studio (última versión estable)
- SDK mínimo / objetivo: *(definir según dispositivos objetivo)*
- Dispositivo físico con cámara y sensores (el emulador **no** sirve para probar sensores
  de movimiento ni cámara real)
- Backend en ejecución y `ApiConfig.kt` apuntando a su URL

## Cómo correr el proyecto

1. Clona el repositorio y ábrelo en Android Studio.
2. Configura la URL del backend en `ApiConfig.kt`.
3. Sincroniza Gradle (`File > Sync Project with Gradle Files`).
4. Ejecuta la configuración `app` en un dispositivo físico.

## Estructura del proyecto

Ver [`ARCHITECTURE.md`](./ARCHITECTURE.md) para la organización de paquetes, capas,
navegación, backend y la especificación de cada vista.

## Estado del proyecto

En desarrollo. Este documento y `ARCHITECTURE.md` se actualizan a medida que el proyecto
avanza; si cambia una decisión de arquitectura, refléjalo también aquí.