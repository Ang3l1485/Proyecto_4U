# Campus Locator

Sistema que **ubica y guía por voz a personas con discapacidad visual dentro de un campus universitario**, usando la
cámara y los sensores del teléfono y un servicio que compara imágenes mediante embeddings (DINOv2).

Este repositorio es un **monorepo**: contiene la app Android, el backend, el servicio de embeddings y la
infraestructura como código. Cada carpeta tiene su propia documentación.

---

## ¿Qué hace?

1. **Ubicarse ("¿dónde estoy?"):** el usuario da una vuelta completa de 360° y la app captura 5 fotos
   automáticamente. El backend las compara contra un dataset de imágenes de referencia y devuelve la posición.
2. **Ir a un lugar ("quiero ir a…"):** tras ubicarse, la app guía por voz paso a paso y avisa de obstáculos
   cercanos (lagos, bancas, escaleras, obras) con alertas escritas por el administrador.
3. **Seguimiento continuo:** la posición se mantiene con navegación inercial (pasos + rumbo) y se corrige con fotos
   automáticas.
4. **Recolección del dataset (administrador):** el admin camina por el campus; la app captura fotos con su
   coordenada, y el backend genera los embeddings y los indexa. También gestiona lugares, alertas, videos y
   estadísticas.

Es **una sola app Android** con dos flujos: el público (usuario final, controlado por voz y compatible con
TalkBack) y el protegido (administrador, tras iniciar sesión con rol `ADMIN`).

---

## Estructura del repositorio

```
campus-locator/
├── .github/workflows/           CI/CD de todo el repositorio
├── FRONTEND_KOTLIN/             App Android (Kotlin + Jetpack Compose)
├── BACKEND_FASTAPI/             API REST (FastAPI)
├── SERVICE_EMBEDDING/           Servicio de embeddings DINOv2
├── INFRASTRUCTURA_TERRAFORM/    Infraestructura como código (Terraform)
└── README.md                    Este archivo
```

| Carpeta | Qué contiene | Documentación |
|---|---|---|
| [`FRONTEND_KOTLIN/`](./FRONTEND_KOTLIN) | App Android: pantallas, voz, cámara, sensores (PDR), mapa | `README.md` y `ARCHITECTURE.md` dentro de la carpeta |
| [`BACKEND_FASTAPI/`](./BACKEND_FASTAPI) | API REST: autenticación, lugares, alertas, dataset, localización | *(por documentar)* |
| [`SERVICE_EMBEDDING/`](./SERVICE_EMBEDDING) | Servicio que convierte fotos en vectores con DINOv2 | *(por documentar)* |
| [`INFRASTRUCTURA_TERRAFORM/`](./INFRASTRUCTURA_TERRAFORM) | Red, cómputo, base de datos, almacenamiento y CI/CD como código | [`ARCHITECTURE.md`](./INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md) |

---

## Cómo encajan las piezas

```
 App Android ──HTTPS──► BACKEND_FASTAPI ──► SERVICE_EMBEDDING (DINOv2)
 (FRONTEND_KOTLIN)           │
        │                    ├──► PostgreSQL + pgvector  (metadatos y vectores)
        │                    └──► Almacenamiento de fotos (S3)
        │
        └──HTTPS──► OpenStreetMap  (teselas del mapa base, directo desde el WebView)

 Todo lo anterior (menos OpenStreetMap) se crea con INFRASTRUCTURA_TERRAFORM.
```

- La app solo necesita **la URL base de la API** (`ApiConfig.kt`).
- El backend es el único que habla con el servicio de embeddings, la base de datos y el almacenamiento.
- El mapa **no pasa por el backend**: la app lo carga directamente desde OpenStreetMap con Leaflet.
- Los contratos exactos entre carpetas (variables de entorno, endpoints, salidas de Terraform) están en
  [`INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md`](./INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md), sección 4, y los
  endpoints esperados por la app en `FRONTEND_KOTLIN/ARCHITECTURE.md`, sección 3.

---

## Tecnologías

| Parte | Tecnología |
|---|---|
| App | Kotlin, Jetpack Compose, CameraX, `TextToSpeech` / `SpeechRecognizer`, TalkBack |
| Posición | Navegación inercial (PDR) con acelerómetro y rotation vector; corrección visual con fotos |
| Mapa | OpenStreetMap + Leaflet dentro de un `WebView`, con capa propia de alertas |
| Backend | Python, FastAPI |
| Embeddings | DINOv2 |
| Datos | PostgreSQL con `pgvector`; fotos en almacenamiento de objetos |
| Infraestructura | Terraform (plan inicial sobre AWS), contenedores Docker, GitHub Actions |

---

## Requisitos generales

- **Git** y una carpeta de trabajo **local**. No guardes el repositorio en Google Drive ni en otra carpeta
  sincronizada: Gradle y Terraform crean miles de archivos temporales y fallan con errores de permisos.
- Para la app: Android Studio (última versión estable) y un **dispositivo físico** con cámara y sensores (el
  emulador no sirve para probar sensores ni cámara).
- Para el backend y el servicio de embeddings: *(por definir: versión de Python, gestor de dependencias y Docker)*.
- Para la infraestructura: Terraform y credenciales de la nube *(ver `INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md`)*.

---

## Cómo empezar

Cada carpeta se trabaja de forma independiente:

1. **App Android:** abre `FRONTEND_KOTLIN/` en Android Studio, configura la URL del backend en `ApiConfig.kt`,
   sincroniza Gradle y ejecuta la configuración `app` en un dispositivo físico. Detalles en
   `FRONTEND_KOTLIN/README.md`.
2. **Backend y embeddings:** *(pendiente: se documentará en el `README.md` de cada carpeta)*.
3. **Infraestructura:** *(pendiente: el plan por fases está en `INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md`)*.

---

## Estado del proyecto

| Parte | Estado |
|---|---|
| `FRONTEND_KOTLIN` | En desarrollo. Flujos público y de administración con varias vistas implementadas; backend simulado con datos de prueba (*stubs*) |
| `BACKEND_FASTAPI` | En desarrollo |
| `SERVICE_EMBEDDING` | En desarrollo |
| `INFRASTRUCTURA_TERRAFORM` | Plan inicial documentado; sin implementar |

---

## Convenciones del repositorio

- **Un repositorio, cuatro carpetas hermanas.** Ninguna contiene a las demás.
- Cada servicio incluye su propio `Dockerfile`; la infraestructura solo sabe qué imagen ejecutar.
- Si cambia una decisión de arquitectura, se actualiza el `ARCHITECTURE.md` de la carpeta afectada **en el mismo
  cambio**, y este archivo si cambia la estructura general.
- Nunca se suben secretos, contraseñas ni archivos de estado de Terraform (`*.tfstate`, `.terraform/`).
- Cuando una carpeta añada una variable de entorno o un endpoint que otra necesite, se documenta primero en la
  sección de contratos de `INFRASTRUCTURA_TERRAFORM/ARCHITECTURE.md`.