# Dataset App

Aplicación Flutter para construir un dataset fotográfico georreferenciado.


## Funciones principales

- Captura individual desde la cámara.
- Secuencia de cinco fotografías y selección automática de la imagen con mejor puntuación de calidad.
- Selección de una imagen desde la galería.
- Lectura de latitud y longitud mediante GPS.
- Lectura del rumbo y conversión a dirección cardinal.
- Validación de resolución, brillo y nitidez antes de guardar.
- Confirmación explícita cuando se desea guardar una imagen rechazada por calidad. Esta decisión queda registrada en `wasQualityOverride`.
- Escritura de la fotografía como JPEG con metadatos EXIF.
- Escritura de un JSON por captura y de un manifiesto general.
- Listado, filtrado por bloque y rango de fechas, edición de metadatos y eliminación individual o múltiple.
- Degradación controlada de las funciones que una plataforma no puede ofrecer. Por ejemplo, la brújula informa que no está disponible en Windows en vez de cerrar la aplicación.

## Arquitectura

El proyecto usa una arquitectura modular por funcionalidad, con dependencias dirigidas hacia el dominio. Evita una Clean Architecture ceremonial: solo conserva las separaciones que protegen las reglas del negocio, facilitan las pruebas y aíslan los plugins.

```text
main.dart
   |
   v
app/composition_root.dart
   |-- crea adaptadores de platform
   |-- crea repositorio de data
   |-- crea casos de uso de domain
   `-- inyecta controladores en presentation

presentation --> domain <-- data
      |                       |
      `------ interfaces -----'

platform --> plugins de Flutter y APIs del dispositivo
```

Las reglas de dependencia son:

- `domain` no depende de Flutter, widgets, archivos ni plugins.
- `data` implementa los contratos definidos en `domain` y conoce la persistencia local.
- `presentation` muestra widgets y llama a controladores/casos de uso; no importa `dart:io`, `camera`, `geolocator`, `image_picker`, `permission_handler` ni `flutter_compass`.
- `platform` encapsula las dependencias específicas del dispositivo detrás de interfaces pequeñas.
- `app/composition_root.dart` es el único lugar que construye y conecta las dependencias concretas.

### Flujo de una captura

```text
CapturePage
  -> CaptureController
     -> CameraService / ImagePickerService
     -> LocationService / CompassService
     -> ValidateCapture
     -> CreateCapture
        -> CaptureRepository
           -> LocalCaptureRepository
              -> ExifMetadataWriter
              -> CaptureFileStore
              -> ManifestStore
```

La UI nunca escribe archivos directamente. El repositorio coordina el guardado para evitar dejar registros parciales: genera el JPEG con EXIF, escribe la imagen y su JSON y solo después actualiza el manifiesto. Ante un error durante la creación elimina los archivos parciales.

## Significado de las carpetas

```text
APK/
|-- android/                  Proyecto nativo y configuración de compilación Android
|-- assets/                   Recursos estáticos conservados por el proyecto
|-- build/                    Salidas generadas; no contiene código fuente
|-- web/                      Archivos de arranque para Flutter Web
|-- windows/                  Runner y configuración CMake para Windows
|-- lib/                      Código de producción Dart
|   |-- app/                  Arranque visual y composición de dependencias
|   |-- core/                 Errores transversales sin reglas de una pantalla
|   |-- features/             Módulos funcionales de la aplicación
|   |   `-- captures/         Funcionalidad completa de capturas
|   |       |-- domain/       Modelos, contratos y reglas de negocio puras
|   |       |-- data/         Persistencia y análisis técnico de imágenes
|   |       `-- presentation/ Pantallas, estado, controladores y widgets
|   `-- platform/             Adaptadores de cámara, GPS, brújula y galería
|-- test/                     Pruebas unitarias y de widgets
|-- pubspec.yaml              Dependencias, versión y configuración de Flutter
`-- analysis_options.yaml     Reglas estáticas de calidad mediante flutter_lints
```

Las carpetas nativas (`android`, `web` y `windows`) no son código muerto: Flutter las necesita para compilar cada plataforma aunque la mayor parte de la lógica esté en `lib/`. `.dart_tool/` y `build/` son salidas generadas y no deben editarse manualmente.

## Responsabilidad de cada módulo

### `lib/main.dart`

Inicializa Flutter, solicita a `CompositionRoot` que construya la aplicación y ejecuta el widget raíz con `runApp`.

### `lib/app/`

- `app.dart`: contiene `DatasetApp`, el tema, la navegación principal y las pestañas de captura y dataset.
- `composition_root.dart`: crea el directorio local de capturas, el repositorio, los casos de uso, los adaptadores de plataforma y los controladores. Los umbrales actuales de calidad también se configuran aquí: mínimo 640×480, brillo 35 y nitidez 8.

Este punto único de composición permite cambiar una implementación, por ejemplo un repositorio local por otro, sin modificar las pantallas.

### `lib/core/`

- `errors/capture_storage_exception.dart`: error descriptivo para fallos de lectura o escritura. Evita filtrar excepciones de bajo nivel hasta la interfaz.

`core` solo contiene conceptos realmente compartidos. No es una carpeta genérica donde colocar cualquier función auxiliar.

### `features/captures/domain/entities/`

- `capture.dart`: representa una captura completa. Conserva identificador, rutas, metadatos, reporte de calidad y si el usuario forzó el guardado.
- `capture_metadata.dart`: representa bloque, coordenadas, fecha, autor, sesión, estado y rumbo opcional. Incluye serialización JSON, `copyWith` y la conversión de grados a dirección cardinal.
- `image_quality_report.dart`: contiene dimensiones, brillo promedio, puntuación de nitidez y motivos de rechazo. `isAccepted` indica si pasó todas las reglas y `selectionScore` sirve para escoger la mejor foto de una secuencia.

Estas entidades son inmutables. Para editar se crea una copia, lo que evita perder campos no modificados como el rumbo o los grados de brújula.

### `features/captures/domain/repositories/`

- `capture_repository.dart`: contrato de persistencia. Declara creación, listado, lectura de imagen, actualización de metadatos y eliminación. `CreateCaptureRequest` agrupa los datos necesarios para crear una captura sin usar una lista extensa de argumentos.

El dominio conoce el contrato `CaptureRepository`, pero no conoce `LocalCaptureRepository` ni el sistema de archivos.

### `features/captures/domain/use_cases/`

| Archivo / clase | Función |
|---|---|
| `capture_validation.dart` | Centraliza las validaciones de metadatos y el error `CaptureValidationException`. |
| `CreateCapture` | Valida los datos y bloquea una imagen rechazada, salvo que `allowQualityOverride` sea una decisión explícita. |
| `ListCaptures` | Obtiene las capturas a través del repositorio. |
| `FilterCaptures` | Aplica en un solo lugar el filtro por bloque y fechas. La fecha final incluye todo el día elegido. |
| `UpdateCaptureMetadata` | Valida los cambios y crea metadatos actualizados conservando todos los valores no editados. |
| `DeleteCaptures` | Elimina el conjunto de identificadores indicado. |
| `ValidateCapture` | Delega el análisis binario de la imagen al contrato `CaptureQualityAnalyzer`. |

Un caso de uso expresa una acción del negocio y no contiene widgets ni acceso directo a plugins.

### `features/captures/data/`

#### `repositories/`

- `local_capture_repository.dart`: implementación local de `CaptureRepository`. Coordina el JPEG, JSON, EXIF y manifiesto; ordena las capturas por fecha, ignora entradas cuyos archivos ya no existen, conserva la imagen al editar y elimina los archivos correspondientes al borrar.

#### `sources/`

- `atomic_file_writer.dart`: reemplaza archivos usando temporales y respaldo para reducir el riesgo de corrupción.
- `capture_file_store.dart`: calcula rutas y lee/escribe/elimina el JPEG y JSON de cada captura.
- `manifest_store.dart`: lee y escribe el índice general de capturas. Un manifiesto inválido produce un error explícito en vez de tratarse silenciosamente como vacío.
- `exif_metadata_writer.dart`: es la única fuente de verdad para convertir metadatos de dominio a EXIF y producir el JPEG final.

#### `services/`

- `image_quality_analyzer.dart`: decodifica la imagen y calcula resolución, brillo promedio y nitidez. Devuelve un `ImageQualityReport`; no decide por sí mismo guardar la captura.

### `features/captures/presentation/capture/`

- `capture_page.dart`: compone la pantalla de captura y muestra confirmaciones y mensajes al usuario.
- `capture_controller.dart`: coordina cámara, galería, GPS, brújula, validación y creación. Expone estado observable mediante `ChangeNotifier` sin acoplar la UI a los plugins.
- `capture_state.dart`: fotografía inmutable del estado de la pantalla: disponibilidad, actividad, imagen pendiente, calidad, rumbo y mensajes.
- `widgets/capture_form.dart`: formulario exclusivo de una captura nueva y validación de sus campos visibles.
- `widgets/camera_preview_panel.dart`: vista previa o explicación de por qué la cámara no está disponible.
- `widgets/capture_actions.dart`: acciones de cámara, secuencia, galería y descarte.
- `widgets/quality_report_card.dart`: visualiza las métricas y motivos de rechazo.

### `features/captures/presentation/dataset/`

- `dataset_page.dart`: organiza filtros, cuadrícula, detalle, edición y confirmación de borrado.
- `dataset_controller.dart`: carga, filtra, selecciona, actualiza y elimina capturas; mantiene el estado coherente después de cada operación.
- `dataset_state.dart`: estado inmutable del listado, selección, filtro, carga y errores.
- `widgets/capture_grid.dart`: cuadrícula seleccionable de fotografías.
- `widgets/capture_detail.dart`: vista de metadatos y calidad de la captura elegida.
- `widgets/capture_editor.dart`: formulario de edición con controladores propios. No comparte `TextEditingController` con el formulario de captura nueva.
- `widgets/dataset_filter_panel.dart`: controles de bloque y rango de fechas.

### `lib/platform/`

Cada integración tiene una interfaz pequeña y una implementación basada en plugins:

| Carpeta | Contrato | Implementación / plugin |
|---|---|---|
| `camera/` | `CameraService` | `FlutterCameraService` usa `camera` y el soporte explícito `camera_windows`. |
| `location/` | `LocationService` | `GeolocatorLocationService` usa `geolocator`. |
| `compass/` | `CompassService` | `FlutterCompassService` usa `flutter_compass`; en Windows informa que no está disponible. |
| `media/` | `ImagePickerService` | `FlutterImagePickerService` usa `image_picker` para la galería. |

Esta separación concentra permisos, disponibilidad por plataforma y tipos de plugins fuera de `presentation`.

### `test/`

Las pruebas cubren serialización de metadatos, conservación de campos al editar, filtros inclusivos, reglas de calidad, creación con rechazo/guardado forzado y operaciones del repositorio local, incluidos manifiestos corruptos y archivos faltantes. Cada prueba de almacenamiento crea su propio directorio temporal.

## Persistencia local

`CompositionRoot` crea una carpeta `captures` dentro del directorio de documentos privado de la aplicación. Allí se almacenan:

```text
captures/
|-- manifest.json
|-- <capture-id>.jpg
`-- <capture-id>.json
```

- El JPEG contiene una copia de los metadatos en EXIF.
- El JSON individual contiene el registro completo de la captura.
- `manifest.json` es el índice utilizado para listar el dataset.
- El identificador combina bloque, instante y sesión, sanitizados para poder usarse como nombre de archivo.

Los datos viven en el almacenamiento privado de la aplicación. Desinstalarla o borrar sus datos puede eliminar el dataset; antes de hacerlo se debe respaldar la información por un mecanismo externo.

## Convenciones de nombres y formato

El proyecto sigue las convenciones oficiales de Dart:

| Elemento | Formato | Ejemplo |
|---|---|---|
| Clases, tipos y enums | `PascalCase` | `CaptureRepository`, `MetadataStatus` |
| Funciones y métodos | `lowerCamelCase`, comenzando con un verbo | `createCapture()`, `loadCaptures()` |
| Variables y parámetros | `lowerCamelCase` | `captureId`, `imageBytes` |
| Booleanos | prefijo `is`, `has`, `can`, `should` o pasado descriptivo | `isSaving`, `hasCameraPermission`, `wasQualityOverride` |
| Colecciones | nombre plural | `captures`, `selectedCaptureIds` |
| Miembros privados | guion bajo y nombre descriptivo | `_manifestStore`, `_setPendingImage()` |
| Archivos y carpetas Dart | `snake_case` | `capture_metadata.dart` |
| Constantes y valores inmutables | `const` o `final` | `final Capture capture` |

Además:

- Las funciones asíncronas declaran el resultado: `Future<Capture>`, `Future<void>` o `Stream<CompassReading>`.
- Las funciones representan una acción específica. Se evitan nombres ambiguos como `process`, `handle`, `data` o `doStuff`.
- Se usan parámetros nombrados y `required` cuando hacen más clara la llamada.
- Cuando una operación necesita varios valores relacionados se usa un objeto, como `CreateCaptureRequest` o `CaptureMetadataChanges`.
- Los modelos usan `copyWith` para producir copias inmutables.
- El formato canónico se aplica con `dart format .` y las reglas se verifican con `flutter analyze` usando `flutter_lints`.

Ejemplo de la convención:

```dart
Future<Capture> createCapture({
  required Uint8List imageBytes,
  required CaptureMetadata metadata,
  required ImageQualityReport quality,
  required bool allowQualityOverride,
}) async {
  // La implementación realiza una única acción de negocio.
}
```

## Preparar el entorno

### VS Code

1. Instalar el Flutter SDK estable y agregar `flutter/bin` al `PATH`.
2. Instalar Visual Studio Code.
3. Instalar las extensiones **Flutter** y **Dart**.
4. Instalar Android Studio con Android SDK, SDK Platform, Build Tools, Command-line Tools y Platform-Tools.
5. Abrir esta carpeta en VS Code, no la carpeta `lib` de forma aislada.
6. Verificar el entorno:

```powershell
flutter --version
flutter doctor -v
flutter doctor --android-licenses
```

Aceptar todas las licencias solicitadas. Visual Studio Code es el editor; no reemplaza a Android Studio/Android SDK para compilar Android.

### Instalar dependencias y validar el proyecto

Desde la raíz, donde está `pubspec.yaml`:

```powershell
cd "C:\Users\user\OneDrive\Documentos\Semestre 7\P2\APK\APK"
flutter pub get
dart format .
flutter analyze
flutter test
```

No se debe generar ni instalar una APK nueva si `flutter analyze` o `flutter test` reportan fallos sin revisar.

## Ejecutar en un celular Android físico

1. En el teléfono, activar **Opciones de desarrollador** y **Depuración USB**.
2. Conectarlo por USB y aceptar la huella RSA mostrada en el teléfono.
3. Comprobar que Flutter lo detecta:

```powershell
flutter devices
```

4. Copiar el identificador mostrado y ejecutar:

```powershell
flutter run -d <id-del-dispositivo>
```

`flutter run` instala una compilación de desarrollo y permite hot reload. La aplicación solicitará permisos de cámara y ubicación en tiempo de ejecución.

Si no aparece el teléfono, verificar primero:

```powershell
adb devices
flutter doctor -v
```

En Windows también puede ser necesario instalar el controlador USB del fabricante.

## Generar y actualizar la APK del celular

### 1. Incrementar la versión

Editar `pubspec.yaml` antes de cada entrega:

```yaml
version: 1.0.1+2
```

- `1.0.1` es la versión visible (`versionName`).
- `2` es el número interno Android (`versionCode`) y debe aumentar en cada actualización.

### 2. Validar y compilar

```powershell
flutter pub get
dart format .
flutter analyze
flutter test
flutter build apk --release
```

La APK universal queda en:

```text
build\app\outputs\flutter-apk\app-release.apk
```

### 3. Instalar como actualización por USB

Con el teléfono conectado y visible en `adb devices`:

```powershell
adb -s <id-del-dispositivo> install -r "build\app\outputs\flutter-apk\app-release.apk"
```

La opción `-r` reemplaza la aplicación conservando sus datos. También se puede copiar `app-release.apk` al teléfono y abrirlo; Android solicitará permiso para instalar aplicaciones desde esa fuente.

Para que Android acepte la APK como actualización deben mantenerse:

- El mismo `applicationId`. Actualmente es `com.example.dataset_app` en `android/app/build.gradle.kts`.
- La misma clave de firma.
- Un `versionCode` superior al instalado.

Actualmente el bloque `release` de `android/app/build.gradle.kts` usa la clave de depuración. Sirve para pruebas internas, pero **no es una configuración de publicación**. Antes de distribuir la aplicación se debe crear y respaldar un keystore de producción, configurar la firma release y conservar esa misma clave para todas las actualizaciones futuras. Cambiar la firma produce `INSTALL_FAILED_UPDATE_INCOMPATIBLE`; desinstalar para solucionarlo borraría los datos privados locales.

## Ejecutar en Windows

Windows requiere **Visual Studio Community** o **Visual Studio Build Tools** con el workload **Desktop development with C++**. Visual Studio Code por sí solo no incluye el compilador de escritorio.

Después de comprobar `flutter doctor -v`:

```powershell
flutter config --enable-windows-desktop
flutter pub get
flutter run -d windows
```

El proyecto incluye el runner de Windows y `camera_windows`. Cámara, selección de imágenes y ubicación dependen de que el equipo, sus permisos y los plugins dispongan de la capacidad correspondiente. La brújula no está disponible en Windows y la aplicación lo comunica de forma explícita.

Para generar una compilación Windows:

```powershell
flutter build windows --release
```

## Permisos Android

`android/app/src/main/AndroidManifest.xml` declara únicamente:

- `CAMERA`
- `ACCESS_FINE_LOCATION`
- `ACCESS_COARSE_LOCATION`

No se solicitan permisos antiguos de almacenamiento porque las capturas se guardan dentro del directorio privado de la aplicación y la galería se abre mediante el selector del sistema.

## Comandos rápidos

```powershell
# Dependencias
flutter pub get

# Formato y calidad
dart format .
flutter analyze
flutter test

# Desarrollo Android
flutter devices
flutter run -d <id-del-dispositivo>

# APK de actualización
flutter build apk --release
adb -s <id-del-dispositivo> install -r "build\app\outputs\flutter-apk\app-release.apk"

# Desarrollo Windows
flutter run -d windows
```

## Limitaciones conocidas

- La brújula no está disponible en Windows.
- La disponibilidad real de cámara, ubicación y galería depende del hardware, permisos y soporte de cada plugin en la plataforma instalada.
- El dataset es local; todavía no existe sincronización en nube ni exportación integrada.
- La firma Android release sigue configurada con la clave de depuración y debe cambiarse antes de una distribución formal.
- El identificador Android `com.example.dataset_app` es provisional; si se cambia después de instalar la app, Android la considerará una aplicación distinta.
