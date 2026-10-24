# Campus Locator

Sistema que **ubica y guía por voz a personas con discapacidad visual dentro de un campus universitario**, usando la
cámara y los sensores del teléfono y un servicio que compara imágenes mediante embeddings (DINOv2).

Este repositorio es un **monorepo**: contiene la app Android, el backend, el servicio de embeddings y la
infraestructura como código. Cada carpeta tiene su propia documentación en `docs/`.

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
├── INFRASTRUCTURA_TERRAFORM/    Infraestructura como código (Terraform, AWS)
└── README.md                    Este archivo
```

Las cuatro carpetas tienen la misma forma:

```
<CARPETA>/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PLAN.md
│   ├── CHANGELOG.md
│   └── validation/
│       └── validation-<fase>-<n>.md     cómo se comprueba el lote <PREFIJO>-<fase>.<n>
└── project/                             todo el código
    └── src/ops/validate<fase><n>.py     el validador automático de ese lote
```

Por ejemplo, el lote `BE-2.2` se describe en `BACKEND_FASTAPI/docs/PLAN.md`, se comprueba según
`BACKEND_FASTAPI/docs/validation/validation-2-2.md` y su validador es `BACKEND_FASTAPI/project/src/ops/validate22.py`.

Documentos de `docs/`:

| Documento | Para qué sirve |
|---|---|
| `docs/ARCHITECTURE.md` | Documento maestro: cómo es la pieza en su versión vigente, cómo funciona cada lote, decisiones (ADR) y riesgos. **Su §5 es la única fuente de verdad de las interfaces que esa carpeta expone** |
| `docs/PLAN.md` | Qué se construye y en qué orden: fases, lotes, dependencias y trazabilidad con las historias de usuario. **Su §3 es la única tabla de estado** de la carpeta |
| `docs/CHANGELOG.md` | Una entrada por versión del `ARCHITECTURE.md`: lote que la motivó, qué cambió, contratos tocados, cómo se verificó y qué quedó pendiente |
| `docs/validation/` | Un documento por lote: precondiciones, comprobaciones automáticas y manuales, datos de prueba y cómo ejecutar su validador. El contrato común de los validadores está en `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11 |

| Carpeta | Qué contiene | Contratos que expone (su §5) |
|---|---|---|
| [`FRONTEND_KOTLIN/`](./FRONTEND_KOTLIN/docs/ARCHITECTURE.md) | App Android: pantallas, voz, cámara, sensores (PDR), mapa | Puentes WebView, almacenamiento local, rutas entre vistas, piezas reutilizables y cómo consume la API |
| [`BACKEND_FASTAPI/`](./BACKEND_FASTAPI/docs/ARCHITECTURE.md) | API REST, localización, ingesta y purga del dataset | API REST, errores, esquema de la base, mensajes de las colas, procesos y parámetros |
| [`SERVICE_EMBEDDING/`](./SERVICE_EMBEDDING/docs/ARCHITECTURE.md) | Servicio interno que convierte fotos en vectores con DINOv2 | API interna, modelo, preprocesamiento, `version_vector` y formato del vector |
| [`INFRASTRUCTURA_TERRAFORM/`](./INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md) | Red, cómputo, datos, secretos, permisos, observabilidad y CI/CD en AWS | Nombres de recursos, outputs de Terraform, variables de entorno y secretos, buckets, colas, IAM y despliegue |

El **catálogo de historias de usuario** del proyecto está en `FRONTEND_KOTLIN/docs/PLAN.md` §5; los demás planes lo
referencian.

---

## Orden global de construcción

Vista derivada para ver de un vistazo qué espera a qué entre carpetas. **Mandan las columnas «Para construir» y «Para
validar» de §2 de cada `docs/PLAN.md`**: si cambian, esta tabla se actualiza en el mismo cambio.

- **Para construir** = lo necesario para escribir el código. Casi todo se puede adelantar en `local` (backend con
  `docker compose`, app con *stubs*).
- **Para validar** = lo que debe estar «Hecho» para ejecutar la validación del lote en `dev` y cerrarlo. Es lo que
  ordena las olas de abajo.

| Ola | Infraestructura | Embeddings | Backend | App | Se logra |
|---|---|---|---|---|---|
| Ya | — | EMB-1.1, EMB-2.1 (código y pruebas en `local`) | BE-1.1 a BE-1.3 (código y pruebas en `local`) | FE-2.3, FE-4.2 y FE-4.3 (no dependen de nadie) | Avance sin AWS |
| 0 | INF-0.1 → INF-0.2 | | | | Estado remoto, CI y presupuesto |
| 1 | INF-1.1 → INF-1.2 → INF-1.3 → INF-1.4 | EMB-1.1 (espera INF-1.3) | BE-1.1 (espera INF-1.3 e INF-1.4) → BE-1.2 (espera INF-1.2) → BE-1.3 | FE-1.1 (espera BE-1.1) → FE-1.2 (espera BE-1.3) | Login real por HTTPS |
| 2 | INF-2.1 | EMB-2.1 | BE-2.1 → BE-2.2 (espera EMB-2.1 e INF-2.1) → BE-2.4 | FE-2.3 → FE-2.1 (espera BE-2.2 y FE-2.3) | Primer recorrido real indexado |
| 3 | INF-3.1 | EMB-3.1; EMB-3.2 (espera BE-2.4 y el dataset real de FE-2.1) | BE-3.1 → BE-2.3 (espera BE-2.2 y BE-3.1); BE-4.1 (espera BE-2.4); BE-3.2 (espera BE-2.4, BE-3.1, EMB-3.1 y EMB-3.2) | FE-3.1, FE-3.3, FE-3.4 (esperan BE-3.1); FE-2.2 (espera BE-2.3); FE-3.2 (espera BE-3.2); FE-3.5 (espera FE-3.2) | Ubicarse en el campus |
| 4 | | | (BE-4.1 ya puede estar hecho desde la ola 3) | FE-4.1 (espera BE-4.1) | Administración completa |
| 5–6 | INF-6.1 | EMB-5.1 | BE-5.1 a BE-6.1 | FE-5.1 a FE-6.1 | Diferido |

**Ruta crítica** (la cadena más larga; un retraso aquí retrasa todo):
INF-0.1 → INF-0.2 → INF-1.1 → INF-1.2 → INF-1.3 → INF-1.4 → BE-1.1 → BE-1.2 → BE-1.3 → BE-2.1 → BE-2.2 → FE-2.1
(recorridos reales) → EMB-3.2 → BE-3.2 → FE-3.2.

Cada validador comprueba sus precondiciones antes de empezar: si un lote de otra carpeta no está listo, termina con
código 2 y el lote queda `Bloqueado` (contrato en `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11).

---

## Cómo encajan las piezas

```
 App Android ──HTTPS──► API Gateway ──► api (FastAPI, ECS Fargate) ──► embedding (DINOv2, ECS Fargate)
 (FRONTEND_KOTLIN)                         │        ▲                        ▲
        │                                  │        │                        │
        │                                  ▼        │                        │
        │                       RDS PostgreSQL + pgvector ◄── worker (ingesta y purga, ECS Fargate)
        │                                                        ▲
        └── PUT con URL prefirmada ──► S3 (fotos del dataset) ──► SQS
        │
        └──HTTPS──► OpenStreetMap  (teselas del mapa base, directo desde el WebView)

 Todo lo anterior (menos OpenStreetMap) se crea con INFRASTRUCTURA_TERRAFORM, en AWS (us-east-1).
```

- La app solo necesita **la URL base de la API** (`ApiConfig.kt` = output `api_base_url` de Terraform + `/v1`).
- El backend es el único que habla con el servicio de embeddings, la base de datos y el almacenamiento. La única
  excepción es la subida de fotos del dataset, que va directo a S3 con una URL firmada por el backend.
- El mapa **no pasa por el backend**: la app lo carga directamente desde OpenStreetMap con Leaflet.
- Cada carpeta es dueña de los contratos que expone y los define en el **§5 de su `docs/ARCHITECTURE.md`**; las
  demás carpetas los enlazan, nunca los copian (tabla de arriba).

---

## Tecnologías

| Parte | Tecnología |
|---|---|
| App | Kotlin, Jetpack Compose, CameraX, `TextToSpeech` / `SpeechRecognizer`, TalkBack |
| Posición | Navegación inercial (PDR) con acelerómetro y rotation vector; corrección visual con fotos |
| Mapa | OpenStreetMap + Leaflet dentro de un `WebView`, con capa propia de alertas |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (asyncpg), Alembic, uv |
| Embeddings | DINOv2 ViT-B/14 (768 dimensiones) con PyTorch en CPU |
| Datos | PostgreSQL 17 con `pgvector` (RDS); fotos en S3; colas SQS |
| Infraestructura | AWS (`us-east-1`): API Gateway HTTP API, ECS Fargate, RDS, S3, SQS, Secrets Manager, CloudWatch. Terraform ≥ 1.10, Docker, GitHub Actions con OIDC |

---

## Requisitos generales

- **Git** y una carpeta de trabajo **local**. No guardes el repositorio en Google Drive ni en otra carpeta
  sincronizada: Gradle y Terraform crean miles de archivos temporales y fallan con errores de permisos.
- Para la app: Android Studio (última versión estable) y un **dispositivo físico** con cámara y sensores (el
  emulador no sirve para probar sensores ni cámara).
- Para el backend y el servicio de embeddings: Python 3.12, [uv](https://docs.astral.sh/uv/) y Docker.
- Para la infraestructura: Terraform ≥ 1.10, AWS CLI y acceso a la cuenta del proyecto
  (`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §3).

---

## Cómo empezar

Cada carpeta se trabaja de forma independiente:

1. **App Android:** abre `FRONTEND_KOTLIN/project/` en Android Studio, configura la URL del backend en `ApiConfig.kt`,
   sincroniza Gradle y ejecuta la configuración `app` en un dispositivo físico. Detalles en
   `FRONTEND_KOTLIN/README.md`.
2. **Backend y embeddings:** aún no hay código; el código irá en `project/` y el orden está en el `docs/PLAN.md` de
   cada carpeta (primeros lotes: BE-1.1 y EMB-1.1, que se pueden adelantar en `local`).
3. **Infraestructura:** aún no hay código; se empieza por el lote INF-0.1 (bootstrap de la cuenta) de
   `INFRASTRUCTURA_TERRAFORM/docs/PLAN.md`.
4. **Orden entre carpetas:** sección «Orden global de construcción».

---

## Estado del proyecto

El estado vive **solo** en la tabla §3 del `docs/PLAN.md` de cada carpeta:
[app](./FRONTEND_KOTLIN/docs/PLAN.md) · [backend](./BACKEND_FASTAPI/docs/PLAN.md) ·
[embeddings](./SERVICE_EMBEDDING/docs/PLAN.md) · [infraestructura](./INFRASTRUCTURA_TERRAFORM/docs/PLAN.md).

---

## Convenciones del repositorio

- **Un repositorio, cuatro carpetas hermanas.** Ninguna contiene a las demás.
- Cada servicio incluye su propio `Dockerfile`; la infraestructura solo sabe qué imagen ejecutar.
- **Cambiar una interfaz:** primero se edita el §5 del `docs/ARCHITECTURE.md` de la carpeta dueña (subiendo su
  versión), se añade la entrada en su `docs/CHANGELOG.md` y después se cambia el código. Si otra carpeta necesita
  adaptarse, abre un lote en su `docs/PLAN.md`.
- **Cerrar un lote:** cumplir sus criterios, pasar su validador en `dev` (código 0) con la evidencia de las
  comprobaciones manuales en el PR, y editar solo su fila en la tabla §3 del `docs/PLAN.md` correspondiente.
- Los workflows solo se disparan con cambios en `<CARPETA>/project/`: editar `docs/` no despliega nada.
- Si cambia una decisión de arquitectura, se actualiza el `docs/ARCHITECTURE.md` de la carpeta afectada **en el
  mismo cambio**, y este archivo si cambia la estructura general.
- Nunca se suben secretos, contraseñas, llaves de AWS ni archivos de estado de Terraform (`*.tfstate`, `.terraform/`).
