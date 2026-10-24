# ARCHITECTURE — Backend (`BACKEND_FASTAPI`)

| Campo | Valor |
|---|---|
| Versión del documento | **0.2.0** (historia en [`CHANGELOG.md`](./CHANGELOG.md)) |
| Fecha | 2026-10-23 |
| Estado | Diseño propuesto. **Aún no hay código** |
| Qué se construye y en qué orden | [`PLAN.md`](./PLAN.md) · cómo se comprueba cada lote: [`validation/`](./validation/) |

El backend es la **única puerta** de la app hacia los datos: autentica, guarda metadatos y vectores en PostgreSQL
+ pgvector, firma las subidas a S3, consume las colas de ingesta y purga, y calcula la posición de la persona a partir
de sus fotos. Es el único componente que habla con el servicio de embeddings, la base de datos y el almacenamiento.

Su **§5 es la única fuente de verdad** de: la API REST (pública, de recolección y de administración), los códigos de
error, el esquema de la base de datos, el formato de los mensajes de las colas, los procesos de la imagen y los
parámetros operativos del backend.

---

## 1. Propósito y alcance

### 1.1 Qué cubre
- API REST para la app Android (flujo público y de administración).
- Algoritmo de localización por similitud de imágenes.
- Ingesta asíncrona del dataset (miniaturas, vectores, estados) y purga de lo borrado.
- Esquema y migraciones de la base.

### 1.2 Qué no cubre
- Cómo se calcula un vector: `SERVICE_EMBEDDING/docs/ARCHITECTURE.md`.
- Recursos de AWS, variables de entorno inyectadas, permisos y despliegue:
  `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md`.
- Seguimiento continuo de la posición (PDR) y fusión con la corrección visual: viven en la app
  (`FRONTEND_KOTLIN/docs/ARCHITECTURE.md` §2.3).
- Cálculo de rutas (diferido, ADR-BE-11).

### 1.3 Regla de contratos
Este documento solo define lo que el backend **expone**. Lo que **consume** se enlaza:

| Consume | Definido en |
|---|---|
| Variables de entorno y secretos (`DB_*`, `JWT_SECRET`, `S3_BUCKET_DATASET`, `SQS_URL_*`, `EMBEDDING_URL`…) | `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.4 |
| Bucket, prefijos y notificación S3 → SQS; atributos de las colas | Infra §5.5 y §5.6 |
| `POST /v1/embed`, `GET /v1/info`, `GET /health/ready` y el formato del vector | `SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5 |

Un cambio de interfaz se hace primero en el §5 del dueño, con entrada en su `CHANGELOG.md`, y luego en el código.

---

## 2. Contexto en el sistema

```
 App Android ──HTTPS──► API Gateway ──VPC Link──► api (FastAPI) ──────HTTP──────► embedding (DINOv2)
      │                                             │   │   │                          ▲
      │ PUT prefirmado                              │   │   └── SendMessage ─► SQS purga ──┐
      ▼                                             │   ▼                                 │
     S3 dataset/ ──ObjectCreated──► SQS ingesta ──► worker ──────────────HTTP──────────────┘
                                                    │   │
                                                    ▼   ▼
                                     PostgreSQL 17 + pgvector  (RDS)
```

| Proceso | Responsabilidad | Toca |
|---|---|---|
| `api` | Endpoints HTTP, autenticación, firma de URLs, localización síncrona, encolar purgas y re-procesados, reconciliador de purgas | RDS, S3 (firmar), SQS (enviar), embedding |
| `worker` | Ingesta (miniatura + vector + estado) y purga (borrar objetos y filas) | RDS, S3 (leer, escribir, borrar), SQS (recibir), embedding |
| `migrate` | Migraciones Alembic y creación del admin inicial | RDS |

Los tres salen de **la misma imagen** con distinto comando (§5.9).

---

## 3. Arquitectura en AWS (vista del backend)

- Corre en ECS Fargate, `X86_64`, como servicios `api` y `worker` y tarea suelta `migrate` (tamaños, horario y
  escalado: infra §3.4).
- `api` recibe tráfico solo desde API Gateway por VPC Link en el puerto `8000`. Detrás de API Gateway: máximo 30 s
  por petición y 10 MB de cuerpo; por eso las fotos del dataset no pasan por la API (ADR-BE-04).
- `worker` escala de 0 a 1 según la profundidad de las colas y **solo dentro del horario de `dev`** (infra §5.10). Fuera
  de horario `embedding` está apagado: `/v1/localize` responde `503 EMBEDDING_NO_DISPONIBLE` y los
  mensajes de ingesta esperan en la cola.
- La base es RDS PostgreSQL 17 con pgvector 0.8.x, accesible solo desde la VPC y con TLS obligatorio.
- Logs a CloudWatch (`/campus-locator/dev/<proceso>`) en una línea JSON por evento (§5.10).
- Despliegue: `backend.yml` construye la imagen, ejecuta `migrate` y actualiza `api` y `worker` (infra §5.9).

---

## 4. Componentes y funcionamiento (por lote)

### 4.1 Estructura del código

```
BACKEND_FASTAPI/
├── docs/
│   ├── ARCHITECTURE.md, PLAN.md, CHANGELOG.md
│   └── validation/              validation-<fase>-<n>.md: cómo se comprueba cada lote (§5.11)
└── project/                     todo el código
    ├── src/
    │   ├── app/
    │   │   ├── main.py          Crea la app, monta routers, middlewares (X-Request-Id, logs, errores) y el reconciliador
    │   │   ├── config.py        Settings (pydantic-settings): lee las variables de infra §5.4 y los parámetros de §5.10
    │   │   ├── api/v1/          Routers: health, auth, localize, places, alerts, collect, admin_*
    │   │   ├── esquemas/        Modelos Pydantic de entrada y salida (son el contrato de §5.3–§5.5)
    │   │   ├── dominio/         Lógica pura y probable sin red ni base: localizacion.py, geo.py, rumbo.py, validaciones.py
    │   │   ├── servicios/       Casos de uso: localizar, recolectar, ingerir, purgar, alertas, lugares, estadisticas
    │   │   ├── db/              Modelos SQLAlchemy, sesión async, consultas (incluida la búsqueda vectorial)
    │   │   ├── clientes/        embedding.py (httpx), s3.py y sqs.py (boto3 en hilos de anyio)
    │   │   ├── seguridad/       jwt.py, hash.py (argon2id), dependencias requiere_admin / usuario_opcional
    │   │   ├── worker.py        Bucle de consumo de las colas (python -m app.worker)
    │   │   └── cli.py           migrar, verificar-esquema, crear-usuario (python -m app.cli …)
    │   └── ops/                 validate<fase><n>.py y comun.py: validadores de los lotes BE-x.y (§5.11)
    ├── migrations/              Alembic
    ├── tests/                   unitarias (dominio), de API (httpx + base efímera), de contrato (esquemas vs §5)
    ├── docker-compose.yml       entorno `local` (§5.11)
    ├── Dockerfile               python:3.12-slim, usuario sin privilegios, puerto 8000
    └── pyproject.toml           uv; ruff; pytest; grupo `ops` para los validadores
```

Reglas internas:
- `dominio/` no importa nada de FastAPI, SQLAlchemy ni boto3: se prueba sin infraestructura.
- Los routers solo validan, llaman a un servicio y traducen errores de dominio a los códigos de §5.6.
- Ningún log incluye tokens, contraseñas, URLs prefirmadas ni bytes de imagen.

### 4.2 BE-1.1 — Base del servicio
FastAPI con un único proceso de uvicorn (la tarea tiene 0,25 vCPU). Middleware que asigna `X-Request-Id` (o
respeta el del cliente) y lo pone en cada log. Manejador global que convierte excepciones en el formato de error de
§5.1. `/v1/health` no toca la base (lo usan la app y el *health check* del contenedor); `/v1/health/ready` sí.

### 4.3 BE-1.2 — Base de datos y migraciones
SQLAlchemy 2 asíncrono sobre `asyncpg`; Alembic para el esquema de §5.7. La primera migración crea la extensión
`vector` y los tipos enumerados. `python -m app.cli migrar` aplica `alembic upgrade head` y luego crea el admin
inicial si no existe ningún usuario `admin` (lee `ADMIN_INICIAL_*`). Es idempotente: se ejecuta en cada despliegue.

### 4.4 BE-1.3 — Autenticación
`POST /v1/auth/login` busca el usuario por correo normalizado (sin espacios, minúsculas), verifica la contraseña con
argon2id y emite un JWT HS256 (§5.2). Respuesta idéntica para «no existe», «contraseña incorrecta» e «inactivo», para
no revelar qué correos existen. Devuelve el token **también** a usuarios `user`: es la app la que decide no abrir el
panel (comportamiento ya implementado en `LoginViewModel`). Cada intento se registra en `auditoria`
(`usuario.login`, con éxito o fallo, sin la contraseña). La dependencia `requiere_admin` valida firma, expiración y
rol en cada endpoint `/v1/admin/*` y `/v1/collect/*`, también en los reservados (que responden `501` solo después de
validar el token).

Usuarios por línea de comandos (§5.9): `crear-usuario` crea o, si el correo ya existe, actualiza nombre, rol y
contraseña y lo reactiva; `desactivar-usuario` lo desactiva (sus tokens dejan de valer, §5.2). No hay borrado de
usuarios: la fila queda por la auditoría.

### 4.5 BE-2.1 — Recolección (subida del dataset)
La app graba sin conexión y sube al terminar (vista 7.5 de la app). Secuencia:
1. `POST /v1/collect/videos` con los metadatos del recorrido y una referencia local (`ref_cliente`, p. ej.
   `rec_0003`). Idempotente por (admin, `ref_cliente`): reintentar no duplica el video.
2. `POST /v1/collect/videos/{id}/images` en lotes de hasta 50: registra cada foto (orden, coordenada, rumbo, hora) y
   devuelve una **URL prefirmada PUT** por foto pendiente. Las fotos ya subidas no reciben URL. Llamarlo de nuevo
   regenera URLs vencidas: así se retoma una subida interrumpida.
3. La app hace `PUT` de cada JPEG directo a S3 con el encabezado firmado `Content-Type: image/jpeg`.
4. S3 avisa a la cola `ingesta`; el `worker` continúa (BE-2.2).
5. `POST /v1/collect/videos/{id}/complete` marca la subida como terminada y devuelve el conteo por estado. La app
   consulta `GET /v1/admin/videos/{id}` para la barra de progreso; ese endpoint y `GET /v1/admin/videos` llegan con
   este lote (el resto de §5.5 sobre videos, con BE-4.1).

**Paso a `subida`.** Una foto pasa de `pendiente_subida` a `subida` cuando el `worker` recibe su evento de S3 (antes
de procesarla) o cuando `complete` comprueba con `HEAD` que el objeto ya está en S3; lo que ocurra primero. Así el
conteo es correcto aunque el `worker` esté apagado (fuera de horario).

**Limpieza de datos de prueba.** `python -m app.cli limpiar-validacion` (§5.9) borra de forma definitiva —filas de
`videos`, `imagenes` y `embeddings`, y sus objetos de `dataset/` y `thumbs/`— los videos cuyo `nombre` y `ref_cliente`
empiezan por `validacion-`. Se ejecuta como tarea suelta con la definición de `worker`, que es la que puede borrar en
S3. Lo usan los validadores mientras no existe el borrado de BE-4.1 (§5.11); nunca toca otros videos.

La clave del objeto sigue el formato de infra §5.5 (`dataset/{video_id}/{imagen_id}.jpg`): el `worker` recupera la
fila de la imagen a partir de la clave sin otra consulta.

### 4.6 BE-2.2 — Worker de ingesta
Bucle con espera larga sobre `ingesta` (hasta 10 mensajes). Antes de recibir comprueba que `embedding` esté listo
(`GET /health/ready`); si no lo está, espera y no toma mensajes (evita que se agoten los 5 reintentos y caigan en la
DLQ mientras el modelo carga). Por cada objeto:
1. Decodifica la clave (las claves de los eventos S3 vienen codificadas como URL) y busca la imagen. Si no existe o
   su video está `eliminado`, borra el mensaje (la purga se ocupará del objeto).
2. Si la imagen ya está `procesada` con el mismo ETag, borra el mensaje (idempotencia ante eventos repetidos).
3. Descarga, valida (JPEG decodificable, ≤ 4 MB, lado menor ≥ 320 px), corrige la orientación EXIF, genera la
   miniatura en `thumbs/…` y una copia reducida en memoria (lado mayor `WORKER_LADO_EMBEDDING_PX`, JPEG calidad 90)
   para el modelo: así cada lote queda muy por debajo del límite de 16 MB de embeddings.
4. Agrupa hasta `WORKER_LOTE_EMBEDDING` (4) imágenes reducidas por llamada a `POST /v1/embed` (prioridad `baja`) y
   guarda cada vector en `embeddings` con la `version_vector` que devuelve el servicio. Lotes pequeños acotan lo que
   espera una localización que llega mientras se procesa un lote (embeddings no interrumpe un lote en curso). Si no
   coincide con la esperada (§5.10), no guarda y lo registra como
   error de configuración.
5. Marca la imagen `procesada` y recalcula el estado del video.

Errores **permanentes** (imagen corrupta, demasiado grande): imagen en `error` con el motivo, mensaje borrado.
Errores **transitorios** (embedding caído, base no disponible): el mensaje no se borra y vuelve a la cola tras la
visibilidad; al quinto intento va a la DLQ y la alarma avisa. Mensajes `reprocesar_imagen` (§5.8) siguen el mismo
camino a partir del paso 3.

### 4.7 BE-2.3 — Resumen del panel
`GET /v1/admin/stats` agrega totales en una consulta (fotos procesadas, lugares, alertas activas, último video). Las
«fotos pendientes de subir» del panel salen de la cola local de la app, no del backend.

### 4.8 BE-2.4 — Diagnóstico de búsqueda
`POST /v1/admin/diagnostico/vecinos` (§5.5) muestra qué devuelve el índice para **una** foto, sin agrupar ni puntuar:
vectoriza la foto con prioridad `baja` (no compite con las localizaciones), busca los `k` vecinos en el índice HNSW de
la versión de vector activa con el mismo `hnsw.ef_search` que `/v1/localize` y **sin** aplicar `LOC_SIM_MIN`, y
devuelve cada vecino con su coordenada, su rumbo y su similitud. Lo usa la herramienta de evaluación de embeddings
(EMB-3.2) para medir *recall* y la distribución de similitudes antes de calibrar BE-3.2; también sirve para
investigar una localización mala. No lo usa la app.

La consulta de vecinos (literal de la versión en el `WHERE` para que se use el índice parcial, §5.7) se escribe aquí
una sola vez y BE-3.2 la reutiliza en el paso 3 de §4.10. Como en la localización, la foto no se guarda en ningún
sitio (ADR-BE-06) y no se registra nada en `eventos_localizacion`.

### 4.9 BE-3.1 — Lugares y alertas (lectura pública y administración)
**Lectura pública.** `GET /v1/places` devuelve todos los lugares (decenas, sin paginación) con la distancia a la
posición si se envía.
`GET /v1/alerts` alimenta la caché local de la app, que debe funcionar sin conexión: sin `desde` entrega la foto
completa de alertas activas (incluidas las de vigencia futura, para que lleguen antes de empezar; la app filtra por
vigencia al anunciar); con `desde` entrega solo lo cambiado y los identificadores borrados
(*tombstones*, 90 días). La app guarda `generado_en` y lo envía como `desde` la próxima vez.

**Administración.**
- Lugares: CRUD con nombre único sin distinguir mayúsculas ni tildes. Al borrar un lugar, sus imágenes quedan sin
  lugar.
- Alertas: el editor de la app trabaja local primero y genera los UUID. `PUT /v1/admin/alerts/{id}` crea o reemplaza
  (idempotente); `DELETE` de un id desconocido responde `204` (así, una alerta creada y borrada antes de sincronizar
  no da error). `POST /v1/admin/alerts/sincronizar` aplica una lista de cambios independientes y devuelve el resultado
  de cada uno: la app quita de «pendientes» solo los que salieron `ok`. Control de concurrencia opcional con
  `If-Match: <version>`.

### 4.10 BE-3.2 — Localización (`POST /v1/localize`)
Algoritmo v1 (ADR-BE-08), con los parámetros de §5.10:
1. **Validar**: 1–5 fotos JPEG, cada una ≤ 1,5 MB; `rumbos` con el mismo largo que `fotos`.
2. **Vectorizar**: una sola llamada a `POST /v1/embed` con prioridad `alta`; las fotos no se guardan en ningún sitio
   (ADR-BE-06).
3. **Buscar**: por cada vector, los `LOC_TOP_K` vecinos por distancia coseno en el índice HNSW de la versión de vector
   activa (`SET LOCAL hnsw.ef_search`). Similitud = `1 − distancia`. Se descartan los vecinos con similitud menor que
   `LOC_SIM_MIN`.
4. **Agrupar** todos los vecinos (de todas las fotos) por cercanía geográfica: se recorren de mayor a menor
   similitud; cada uno se une al primer grupo cuyo centroide esté a menos de `LOC_RADIO_GRUPO_M`, o abre uno nuevo.
5. **Puntuar** cada grupo como la suma, sobre las fotos de la consulta, de la mejor similitud que esa foto aporta al
   grupo. Premia los lugares que coinciden con **varias direcciones** de la vuelta, no con una sola foto.
6. **Posición**: centroide del mejor grupo ponderado por `similitud ^ LOC_PESO_EXPONENTE`. Radio de incertidumbre =
   desviación ponderada de las distancias al centroide, con mínimo `LOC_RADIO_MIN_M`.
7. **Confianza** (0–1): `0,5 · s + 0,3 · c + 0,2 · m`, donde `s` es la mejor similitud del grupo normalizada entre
   `LOC_SIM_MIN` y `LOC_SIM_ALTA`; `c` la fracción de fotos con al menos una coincidencia en el grupo; `m` el margen
   relativo frente al segundo grupo. Nivel `alta`, `media` o `baja` según los cortes de §5.10.
8. **Corrección de rumbo**: para cada foto con coincidencia en el grupo, diferencia circular entre el rumbo de la foto
   del dataset y el rumbo informado por el teléfono. Si hay ≥ 2 y su dispersión circular es ≤ 30°, se devuelve la
   media como `correccion_rumbo_grados` (la app la suma a su brújula); si no, `null`.
9. **Contexto**: lugar más cercano a ≤ 60 m y hasta 3 referencias a ≤ 150 m con su rumbo absoluto desde la
   posición (la app lo convierte en «a tu derecha», «al frente»…).
10. Registra un evento anónimo en `eventos_localizacion` (sin fotos, sin identificadores del dispositivo).

Sin vecinos por encima del umbral (o dataset vacío) la respuesta es `200` con `resultado = "sin_coincidencias"`.
Presupuesto de tiempo: embedding ≤ 20 s (límite duro), búsquedas < 100 ms; objetivo p95 total ≤ 5 s.

### 4.11 BE-4.1 — Administración de videos e imágenes, y purga
- Listado, detalle (con URLs prefirmadas GET de 1 h para foto y miniatura), renombrar, re-procesar y edición de
  imágenes (coordenada, lugar, calidad, notas). Corregir la coordenada **no** exige recalcular el vector: el vector
  solo depende de los píxeles.
- **Borrar un video** (ADR-BE-07): en una sola transacción, el video pasa a `eliminado`, se borran los vectores de sus
  imágenes (salen de la búsqueda **de inmediato**) y se escribe la auditoría; después se encola `purgar_video`. El
  `worker` borra los objetos de `dataset/` y `thumbs/` y las filas de `imagenes`, y marca `purgado_en`. El video
  queda como registro histórico. Cualquier admin puede borrar cualquier video; queda quién y cuándo.
- **Borrar una imagen**: mismo patrón (`purgar_imagen`).
- **Reconciliador** en `api`: cada 10 min re-encola las purgas de videos borrados hace más de 10 min sin `purgado_en`
  (cubre un fallo al enviar a SQS justo después del commit).

### 4.12 Lotes diferidos (Fase 5)
- **BE-5.1** `POST /v1/localize/frame`: una foto + posición previa; restringe la búsqueda a un radio alrededor de esa
  posición. Hoy responde `501`.
- **BE-5.2** `POST /v1/eventos` y `GET /v1/admin/stats/uso`: eventos anónimos de uso (rutas iniciadas y completadas,
  destinos buscados, alertas anunciadas) para la vista 7.15. Hoy `501`.
- **BE-5.3** `GET /v1/route`: grafo de caminos y ruta más corta (decisión abierta 2 del frontend). Hoy `501`.

---

## 5. Interfaces (contratos)

> **Única fuente de verdad** de lo que expone el backend. Cambiar algo aquí sube la versión de este documento y exige
> entrada en `CHANGELOG.md`; la app y los demás servicios se adaptan en un lote de su `PLAN.md`.

### 5.1 Convenciones generales

| Tema | Regla |
|---|---|
| URL base | `{api_base_url}/v1` (`api_base_url`: output de infra §5.2). En la app, `ApiConfig.kt` |
| Formato | JSON UTF-8, nombres en español y `snake_case`. Valores enumerados en minúsculas (`admin`, `alta`, `biblioteca`) |
| Fechas | ISO-8601 en UTC con `Z`: `2026-10-23T15:04:05Z` |
| Coordenadas | WGS84 en grados decimales: `lat` ∈ [−90, 90], `lng` ∈ [−180, 180] |
| **Rumbo** | Grados en **[0, 360)**, 0 = **norte verdadero** (geográfico), sentido horario. `null` si se desconoce (ADR-BE-12) |
| Distancias / radios | Metros (`distancia_m`, `radio_m`) |
| Identificadores | UUID v4 en minúsculas. Los videos tienen además `numero` (entero creciente) |
| Autenticación | `Authorization: Bearer <jwt>` en `/v1/admin/*` y `/v1/collect/*`. Los endpoints públicos no la requieren |
| Correlación | Encabezado `X-Request-Id` en todas las respuestas; si la petición lo trae, se reutiliza |
| Errores | `{"error": {"codigo": "TEXTO_FIJO", "mensaje": "texto para humanos", "detalle": {…} \| null}}` (códigos en §5.6) |
| Paginación | `?pagina=1&por_pagina=24` (máx. 100) → `{"items": […], "total": 123, "pagina": 1, "por_pagina": 24}` |
| Tamaño | Cuerpo ≤ 10 MB y respuesta en ≤ 30 s (límites de API Gateway). Respuestas generadas por API Gateway (429, 413, 503/504 de *timeout*) llegan con cuerpo `{"message": "…"}`, **no** con el formato de error de arriba: la app debe tratarlas por código HTTP |

### 5.2 JWT

- Algoritmo `HS256`, clave `JWT_SECRET` (infra §5.4) usada **como texto**: los bytes UTF-8 de la cadena base64, sin
  decodificarla. Emisor `iss = "campus-locator-api"`.
- Claims: `sub` (id del usuario), `rol` (`admin` \| `user`), `nombre`, `iat`, `exp` (`iat` + `JWT_TTL_MIN`), `jti`.
- Sin *refresh token*: al vencer, la app vuelve a Login (la app ya borra la sesión en cada arranque en frío).
- Rechazos: sin encabezado → `401 NO_AUTENTICADO`; firma inválida → `401 TOKEN_INVALIDO`; vencido →
  `401 TOKEN_EXPIRADO`; rol distinto de `admin` en una ruta de admin → `403 SIN_PERMISOS`; usuario desactivado después
  de emitir el token → `401 TOKEN_INVALIDO`.

### 5.3 Endpoints públicos

| Método y ruta | Uso en la app | Lote que lo entrega |
|---|---|---|
| `GET /v1/health` | Indicador de conexión de Inicio (6.1) | BE-1.1 |
| `GET /v1/health/ready` | Diagnóstico | BE-1.1 |
| `POST /v1/auth/login` | Login (7.1) | BE-1.3 |
| `POST /v1/localize` | Escaneo 360° → Resultado (6.2, 6.3) | BE-3.2 |
| `GET /v1/places` | Selección de destino (6.4) | BE-3.1 |
| `GET /v1/alerts` | Caché local de alertas (2.5, 6.3, 6.5) | BE-3.1 |
| `POST /v1/localize/frame` | Corrección visual en navegación (6.5) | BE-5.1 (hasta entonces `501`) |
| `GET /v1/route` | Ruta a un destino (6.5) | BE-5.3 (hasta entonces `501`) |
| `POST /v1/eventos` | Estadísticas de uso (7.15) | BE-5.2 (hasta entonces `501`) |

#### `GET /v1/health`
`200` → `{"estado": "ok", "version": "0.1.0", "commit": "<sha corto>"}`. No consulta la base ni embeddings.

#### `GET /v1/health/ready`
`200` → `{"estado": "ok", "db": "ok" | "no_configurada", "embedding": "ok" | "no_disponible"}`. `no_configurada` solo
se ve en BE-1.1, antes de que exista la conexión a la base (BE-1.2). `503 BASE_NO_DISPONIBLE` si la base no
responde. Que `embedding` esté apagado (fuera de horario) **no** produce `503`.

#### `POST /v1/auth/login`
Petición:
```json
{ "identificador": "admin@campus.edu.co", "password": "••••••" }
```
`200`:
```json
{
  "token": "eyJhbGciOi…",
  "expira_en": "2026-10-24T03:04:05Z",
  "usuario": { "id": "7c1e…", "nombre": "Alejandro Gómez", "correo": "admin@campus.edu.co", "rol": "admin" }
}
```
Errores: `401 CREDENCIALES_INVALIDAS` (correo inexistente, contraseña incorrecta o usuario inactivo, sin distinguir),
`422 VALIDACION`, `429` de API Gateway.

#### `POST /v1/localize`
`multipart/form-data` con:
- `fotos`: 1 a 5 partes `image/jpeg`, cada una ≤ 1,5 MB. Recomendado: lado mayor 1024 px, calidad 85.
- `metadatos`: una parte de texto con JSON:
```json
{ "rumbos": [12.0, 84.5, 156.0, 228.3, 300.1], "origen": "escaneo", "app_version": "0.9.0" }
```
`rumbos[i]` es el rumbo (norte verdadero, [0, 360)) de `fotos[i]`, o `null`. `origen` ∈ {`escaneo`}.

`200`:
```json
{
  "resultado": "ok",
  "posicion": { "lat": 6.200104, "lng": -75.578612, "radio_m": 8.5 },
  "confianza": 0.78,
  "nivel": "alta",
  "correccion_rumbo_grados": -6.0,
  "lugar_cercano": { "id": "3f2a…", "nombre": "Biblioteca Central", "distancia_m": 12.4 },
  "referencias": [
    { "id": "9b0c…", "nombre": "Bloque de los Trillizos", "distancia_m": 35.2, "rumbo_grados": 95.0 }
  ],
  "fotos_usadas": 5,
  "fotos_con_coincidencia": 4,
  "version_vector": "dinov2-vitb14/pp-v1",
  "latencia_ms": 2140
}
```
- `resultado` ∈ {`ok`, `sin_coincidencias`}. Con `sin_coincidencias`: `posicion`, `nivel`, `correccion_rumbo_grados`
  y `lugar_cercano` son `null`, `confianza` es `0` y `referencias` está vacía.
- `nivel` ∈ {`alta`, `media`, `baja`}. La app decide qué decir; con `baja` debería sugerir repetir la vuelta (6.3).
- `referencias[].rumbo_grados`: rumbo absoluto desde `posicion` hacia el lugar.

Errores: `400 FOTOS_INVALIDAS` (cantidad, tipo, tamaño o `rumbos` de distinto largo; `detalle.indice` señala la
foto), `503 EMBEDDING_NO_DISPONIBLE` (apagado, caído o sin respuesta en 20 s), `503 BASE_NO_DISPONIBLE`.

#### `GET /v1/places`
Parámetros opcionales: `lat`, `lng` (ambos o ninguno), `categoria`.

`200` → `{"items": [LugarPublico…], "total": 6}`, ordenado por `distancia_m` si se envió posición; si no, por nombre.

`LugarPublico`:
```json
{
  "id": "3f2a…", "nombre": "Biblioteca Central", "categoria": "biblioteca",
  "lat": 6.2009, "lng": -75.5783, "alias": ["biblioteca", "la biblioteca"],
  "descripcion": "Edificio de tres pisos…", "referencias": "Frente al lago…",
  "imagen_url": null, "distancia_m": 85.0
}
```
`categoria` ∈ {`biblioteca`, `cafeteria`, `bano`, `bloque`, `auditorio`, `deportes`, `administracion`, `entrada`}
(los mismos valores que `CategoriaLugar` de la app, en minúsculas). `distancia_m` es `null` sin posición.
`imagen_url` es una URL prefirmada de 1 h o `null`.

#### `GET /v1/alerts`
Parámetro opcional: `desde` (fecha ISO-8601 tomada de un `generado_en` anterior).

`200`:
```json
{
  "generado_en": "2026-10-23T15:04:05Z",
  "completo": true,
  "alertas": [ Alerta… ],
  "eliminadas": []
}
```
- Sin `desde`, o con un `desde` anterior a 90 días: `completo = true`, `alertas` = todas las activas (también las de
  vigencia pasada o futura), `eliminadas` vacía. La app **reemplaza** su caché.
- Con `desde`: `completo = false`, `alertas` = todas las modificadas después de `desde` (activas o no),
  `eliminadas` = ids borrados después de `desde`. La app actualiza su caché (quita las que llegan con `activa = false`
  y las de `eliminadas`); la vigencia la evalúa al anunciar (abajo).

`Alerta`:
```json
{
  "id": "1d6e…", "lat": 6.2011, "lng": -75.5790,
  "mensaje": "Ten cuidado, hay un lago alrededor de la biblioteca",
  "tipo": "agua", "prioridad": "alta", "radio_m": 15, "activa": true,
  "vigencia_desde": null, "vigencia_hasta": null,
  "actualizado_en": "2026-10-22T20:11:00Z", "version": 3
}
```
`tipo` ∈ {`agua`, `mobiliario`, `escalones`, `obra`, `vehiculos`, `otro`}; `prioridad` ∈ {`normal`, `alta`};
`radio_m` entero en [5, 100]. Vigente = `vigencia_desde` nula o pasada, y `vigencia_hasta` nula o futura. **La vigencia
la evalúa la app** en el momento de anunciar, porque una alerta puede empezar a regir sin que nada cambie en el
servidor.

#### Endpoints reservados
`POST /v1/localize/frame`, `GET /v1/route` y `POST /v1/eventos` responden hoy `501 NO_IMPLEMENTADO`. Su contrato se
definirá aquí antes de implementarlos (Fase 5). El reservado de administración, `GET /v1/admin/stats/uso` (§5.5),
exige primero el token de admin (`401`/`403`) y después responde `501`.

### 5.4 Endpoints de recolección (requieren `admin`)

#### `POST /v1/collect/videos`
```json
{
  "ref_cliente": "rec_0003",
  "nombre": "video_3",
  "iniciado_en": "2026-10-20T14:00:00Z", "finalizado_en": "2026-10-20T14:08:32Z",
  "duracion_s": 512, "distancia_m": 340.5, "pasos": 470,
  "inicio": { "lat": 6.2001, "lng": -75.5786, "rumbo": 90.0 },
  "total_fotos": 120,
  "dispositivo": "Xiaomi 23028RA60L / Android 14", "app_version": "0.9.0"
}
```
- `ref_cliente` (1–40 caracteres) es obligatorio. `nombre` opcional (1–40 tras recortar; vacío → `video_<numero>`).
  `total_fotos` ∈ [0, 200].
- `201` → `VideoResumen` (§5.5) con `estado = "pendiente"`. Si ya existe un video del mismo admin con ese
  `ref_cliente`: `200` con el mismo video (idempotente).

#### `POST /v1/collect/videos/{video_id}/images`
```json
{
  "imagenes": [
    { "orden": 1, "lat": 6.2001, "lng": -75.5786, "rumbo": 90.0, "capturada_en": "2026-10-20T14:00:05Z", "bytes": 345678 }
  ]
}
```
- 1 a 50 elementos; `orden` ∈ [1, 200] y único dentro del video; `bytes` ≤ 4 MB (4 194 304); `rumbo` puede ser `null`.
- `200`:
```json
{
  "imagenes": [
    {
      "orden": 1, "id": "a91f…", "estado": "pendiente_subida",
      "subida": {
        "metodo": "PUT",
        "url": "https://campus-locator-dev-dataset-648617469176.s3.amazonaws.com/dataset/…?X-Amz-…",
        "encabezados": { "Content-Type": "image/jpeg" },
        "expira_en": "2026-10-23T15:19:05Z"
      }
    }
  ]
}
```
- Idempotente por (`video_id`, `orden`): repetir actualiza los metadatos mientras la foto siga `pendiente_subida` y
  devuelve URLs nuevas. Si la foto ya está `subida`, `procesada` o `error`, `subida` es `null`.
- La app sube con `PUT` a `url`, enviando **exactamente** los `encabezados` indicados y el JPEG como cuerpo. S3
  responde `200`; una URL vencida da `403` de S3 → pedir URLs de nuevo.
- Errores: `404 NO_ENCONTRADO`, `409 VIDEO_ELIMINADO`, `422 VALIDACION`.

#### `POST /v1/collect/videos/{video_id}/complete`
Sin cuerpo. Antes de responder hace `HEAD` en S3 de las fotos que siguen `pendiente_subida` y pasa a `subida` las que
ya existen (§4.5). `200` →
```json
{ "id": "…", "estado": "procesando", "conteo": { "pendiente_subida": 0, "subida": 37, "procesada": 83, "error": 0 } }
```
Repetirlo es seguro.

### 5.5 Endpoints de administración (requieren `admin`)

**Objetos comunes**

`VideoResumen`:
```json
{
  "id": "…", "numero": 12, "nombre": "Entrada norte", "estado": "procesado",
  "creado_en": "…", "iniciado_en": "…", "finalizado_en": "…",
  "duracion_s": 512, "distancia_m": 340.5, "pasos": 470,
  "inicio": { "lat": 6.2001, "lng": -75.5786, "rumbo": 90.0 },
  "total_fotos": 120,
  "conteo": { "pendiente_subida": 0, "subida": 0, "procesada": 118, "error": 2 },
  "creado_por": { "id": "…", "nombre": "Alejandro Gómez" }
}
```
`estado` del video ∈ {`pendiente` (faltan fotos por subir), `procesando`, `procesado` (todas procesadas),
`con_errores` (ninguna pendiente y al menos una en error), `eliminado`}. Los videos `eliminado` no aparecen en los
listados.

`ImagenAdmin`:
```json
{
  "id": "…", "video_id": "…", "orden": 7,
  "lat": 6.2003, "lng": -75.5788, "rumbo": 182.0, "capturada_en": "…",
  "estado": "procesada", "error": null, "calidad": "normal",
  "lugar": { "id": "…", "nombre": "Biblioteca Central" },
  "notas": null,
  "url": "https://…", "url_miniatura": "https://…", "url_expira_en": "…"
}
```
`estado` de la imagen ∈ {`pendiente_subida`, `subida`, `procesada`, `error`}; `calidad` ∈ {`alta`, `normal`, `baja`};
`url` y `url_miniatura` son prefirmadas GET de 1 h (`null` mientras no existan).

`LugarAdmin` = `LugarPublico` sin `distancia_m`, más `creado_en`, `actualizado_en` y `total_fotos`.

`AlertaAdmin` = `Alerta` más `creado_en`, `creado_por` y `actualizado_por` (`{id, nombre}`).

Lote que entrega cada grupo: `GET /v1/admin/videos` y `GET /v1/admin/videos/{id}`, BE-2.1; `GET /v1/admin/stats`,
BE-2.3; diagnóstico, BE-2.4; lugares y alertas, BE-3.1; el resto de videos y todas las de imágenes, BE-4.1.

| Método y ruta | Petición | Respuesta |
|---|---|---|
| `GET /v1/admin/stats` | — | `200` `{"total_fotos": 2842, "total_lugares": 48, "alertas_activas": 3, "ultimo_video": {"numero": 12, "creado_en": "…"} \| null}`. `total_fotos` = imágenes `procesada` de videos no eliminados |
| `GET /v1/admin/videos` | `?q=&orden=fecha\|nombre\|fotos&dir=desc\|asc&pagina&por_pagina` | Página de `VideoResumen` |
| `GET /v1/admin/videos/{id}` | — | `VideoResumen` + `"fotos": [ImagenAdmin…]` en orden |
| `PATCH /v1/admin/videos/{id}` | `{"nombre": "Entrada norte"}` (1–40 tras recortar) | `200` `VideoResumen` |
| `DELETE /v1/admin/videos/{id}` | — | `202` `{"id": "…", "estado": "eliminado", "fotos_retiradas": 120, "purga": "programada"}`. Repetir da la misma respuesta |
| `GET /v1/admin/images` | `?video_id&lugar_id&estado&calidad&q&pagina&por_pagina` | Página de `ImagenAdmin`, por video (más reciente primero) y `orden` |
| `GET /v1/admin/images/{id}` | — | `ImagenAdmin` + `"video": {id, numero, nombre}` + `"vector": {"version_vector", "creado_en"} \| null` |
| `PATCH /v1/admin/images/{id}` | Cualquiera de: `lat`+`lng` (juntos), `lugar_id` (o `null`), `calidad`, `notas` (≤ 500) | `200` `ImagenAdmin` |
| `DELETE /v1/admin/images/{id}` | — | `204`. Retira el vector al instante y encola `purgar_imagen` |
| `POST /v1/admin/images/lote` | `{"accion": "eliminar" \| "reasignar", "ids": [≤ 200], "lugar_id": "…" \| null}` | `200` `{"procesadas": 10, "fallidas": [{"id": "…", "codigo": "NO_ENCONTRADO"}]}` |
| `POST /v1/admin/images/{id}/reprocesar` | — | `202`; la imagen vuelve a `subida` y se encola `reprocesar_imagen` |
| `GET /v1/admin/places` | `?q=&categoria=` | `{"items": [LugarAdmin…], "total": n}` |
| `POST /v1/admin/places` | `LugarEntrada` | `201` `LugarAdmin` |
| `PUT /v1/admin/places/{id}` | `LugarEntrada` | `200` `LugarAdmin` |
| `DELETE /v1/admin/places/{id}` | — | `204`; sus imágenes quedan con `lugar = null` |
| `GET /v1/admin/alerts` | `?q=&tipo=&prioridad=&activa=` | `{"items": [AlertaAdmin…], "total": n}` (sin borradas) |
| `PUT /v1/admin/alerts/{id}` | `AlertaEntrada`; opcional `If-Match: <version>` | `201` si se creó, `200` si se reemplazó; cuerpo `AlertaAdmin` |
| `DELETE /v1/admin/alerts/{id}` | — | `204`, también si no existe |
| `POST /v1/admin/alerts/sincronizar` | `{"cambios": [{"op": "upsert", "alerta": {"id": "…", …AlertaEntrada}}, {"op": "eliminar", "id": "…"}]}` (≤ 100) | `200` `{"generado_en": "…", "resultados": [{"id": "…", "op": "upsert", "estado": "ok" \| "error", "codigo": null \| "VALIDACION"}]}` |
| `GET /v1/admin/stats/uso` | — | BE-5.2 (hasta entonces `501`) |
| `POST /v1/admin/diagnostico/vecinos` | `multipart/form-data` con una foto; `?k=` | Ver abajo (BE-2.4) |

`LugarEntrada`: `nombre` (2–80), `categoria`, `lat`, `lng`, `alias` (≤ 20 textos de ≤ 60), `descripcion` (≤ 300),
`referencias` (≤ 300). Nombre único sin distinguir mayúsculas ni tildes → `409 NOMBRE_DUPLICADO`.

`AlertaEntrada`: `lat`, `lng`, `mensaje` (1–200 tras recortar), `tipo` (por defecto `otro`), `prioridad` (por defecto
`normal`), `radio_m`
(5–100, por defecto 15), `activa` (por defecto `true`), `vigencia_desde`, `vigencia_hasta` (si ambas,
`hasta > desde`). En `sincronizar`, cada cambio es independiente: un error no revierte los demás.

#### `POST /v1/admin/diagnostico/vecinos`
`multipart/form-data` con una sola parte `foto` (`image/jpeg`, ≤ `LOC_MAX_BYTES_FOTO`, las mismas reglas que una foto
de `/v1/localize`). Parámetro `k` en la URL: entero de 1 a 50, por defecto 5.

`200`:
```json
{
  "version_vector": "dinov2-vitb14/pp-v1",
  "k": 5,
  "vecinos": [
    { "imagen_id": "…", "video_id": "…", "lat": 6.2003, "lng": -75.5788, "rumbo": 182.0,
      "lugar_id": "3f2a…", "similitud": 0.83 }
  ],
  "latencia_ms": 950
}
```
- `vecinos` va de mayor a menor `similitud` (`1 − distancia coseno`) y tiene `k` elementos, o menos si el índice tiene
  menos vectores (vacío si no hay dataset). Solo incluye imágenes con vector de la versión activa; `lugar_id` puede ser
  `null`.
- No aplica `LOC_SIM_MIN` ni agrupa: es la salida cruda del paso 3 de §4.10 para una foto.

Errores: `400 FOTOS_INVALIDAS` (falta la foto, tipo o tamaño; `detalle.indice = 0`), `422 VALIDACION` (`k`),
`503 EMBEDDING_NO_DISPONIBLE`, `503 BASE_NO_DISPONIBLE`, y los de §5.2 y `403 SIN_PERMISOS`.

### 5.6 Códigos de error

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 400 | `SOLICITUD_INVALIDA` | Cuerpo mal formado (JSON inválido, multipart roto) |
| 400 | `FOTOS_INVALIDAS` | `/v1/localize` y `/v1/admin/diagnostico/vecinos`: cantidad, tipo o tamaño de fotos, o `rumbos` incoherente |
| 401 | `NO_AUTENTICADO` · `TOKEN_INVALIDO` · `TOKEN_EXPIRADO` | §5.2 |
| 401 | `CREDENCIALES_INVALIDAS` | Login fallido |
| 403 | `SIN_PERMISOS` | Token válido sin rol `admin` |
| 404 | `NO_ENCONTRADO` | Recurso inexistente (o video eliminado en rutas de lectura) |
| 409 | `NOMBRE_DUPLICADO` · `VIDEO_ELIMINADO` · `CONFLICTO_VERSION` | Lugar repetido · subir fotos a un video borrado · `If-Match` no coincide |
| 422 | `VALIDACION` | Campos fuera de rango; `detalle.campos` = `[{"campo": "radio_m", "motivo": "…"}]` |
| 500 | `ERROR_INTERNO` | Fallo no previsto (el `X-Request-Id` permite encontrarlo en los logs) |
| 501 | `NO_IMPLEMENTADO` | Endpoints reservados |
| 503 | `EMBEDDING_NO_DISPONIBLE` · `BASE_NO_DISPONIBLE` | Dependencia caída, apagada o lenta |

### 5.7 Esquema de la base de datos

PostgreSQL 17 con la extensión `vector` (pgvector 0.8.x). Los UUID se generan con `gen_random_uuid()`, nativo de
PostgreSQL. Todas las fechas son `timestamptz`.

**Tipos enumerados**
`rol_usuario` (`user`, `admin`) · `categoria_lugar` (8 valores de §5.3) · `tipo_alerta` (6 valores) ·
`prioridad_alerta` (`normal`, `alta`) · `estado_video` (`pendiente`, `procesando`, `procesado`, `con_errores`,
`eliminado`) · `estado_imagen` (`pendiente_subida`, `subida`, `procesada`, `error`) · `calidad_imagen` (`alta`,
`normal`, `baja`).

**`usuarios`**

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | `uuid` | PK, `gen_random_uuid()` |
| `correo` | `text` | único, guardado en minúsculas y sin espacios |
| `nombre` | `text` | no nulo |
| `rol` | `rol_usuario` | por defecto `user` |
| `hash_password` | `text` | argon2id |
| `activo` | `boolean` | por defecto `true` |
| `creado_en`, `ultimo_acceso_en` | `timestamptz` | |

**`lugares`**

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | `uuid` | PK |
| `nombre` | `text` | 2–80 |
| `nombre_normalizado` | `text` | único; minúsculas y sin tildes (lo calcula la aplicación) |
| `categoria` | `categoria_lugar` | |
| `lat`, `lng` | `double precision` | rangos WGS84 |
| `alias` | `text[]` | por defecto `{}` |
| `descripcion`, `referencias` | `text` | ≤ 300 |
| `imagen_key` | `text` | clave en `lugares/` o nulo |
| `creado_en`, `actualizado_en` | `timestamptz` | |
| `creado_por` | `uuid` | FK `usuarios` |

**`alertas`**

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | `uuid` | PK; lo puede generar la app |
| `lat`, `lng` | `double precision` | |
| `mensaje` | `text` | 1–200 |
| `tipo` / `prioridad` | enumerados | |
| `radio_m` | `smallint` | 5–100, por defecto 15 |
| `activa` | `boolean` | por defecto `true` |
| `vigencia_desde`, `vigencia_hasta` | `timestamptz` | nulos o `hasta > desde` |
| `version` | `integer` | empieza en 1, +1 en cada cambio |
| `creado_en`, `actualizado_en` | `timestamptz` | índice en `actualizado_en` |
| `creado_por`, `actualizado_por` | `uuid` | FK `usuarios` |
| `eliminada_en` | `timestamptz` | *tombstone*; filas borradas hace > 90 días se eliminan físicamente |

**`videos`**

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | `uuid` | PK |
| `numero` | `integer` | único, secuencia `videos_numero_seq` |
| `nombre` | `text` | 1–40 |
| `ref_cliente` | `text` | único junto con `creado_por` |
| `estado` | `estado_video` | |
| `iniciado_en`, `finalizado_en` | `timestamptz` | informados por la app |
| `duracion_s`, `pasos` | `integer` | |
| `distancia_m` | `real` | |
| `inicio_lat`, `inicio_lng` | `double precision` | |
| `inicio_rumbo` | `real` | [0, 360) o nulo |
| `total_fotos_declaradas` | `smallint` | 0–200 |
| `dispositivo`, `app_version` | `text` | |
| `subida_completa_en` | `timestamptz` | |
| `creado_por` | `uuid` | FK `usuarios` |
| `creado_en`, `actualizado_en` | `timestamptz` | |
| `eliminado_en`, `eliminado_por`, `purgado_en` | | borrado lógico y purga |

**`imagenes`**

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | `uuid` | PK |
| `video_id` | `uuid` | FK `videos` (`ON DELETE CASCADE`) |
| `orden` | `smallint` | 1–200; único junto con `video_id` |
| `s3_key` | `text` | único; formato de infra §5.5 |
| `lat`, `lng` | `double precision` | |
| `rumbo` | `real` | [0, 360) o nulo |
| `capturada_en` | `timestamptz` | |
| `bytes_declarados`, `bytes` | `integer` | |
| `etag` | `text` | |
| `ancho`, `alto` | `smallint` | tras corregir EXIF |
| `estado` | `estado_imagen` | índice |
| `error` | `text` | motivo legible |
| `intentos` | `smallint` | por defecto 0 |
| `calidad` | `calidad_imagen` | por defecto `normal` |
| `lugar_id` | `uuid` | FK `lugares` (`ON DELETE SET NULL`), índice |
| `notas` | `text` | ≤ 500 |
| `creado_en`, `actualizado_en` | `timestamptz` | |

**`embeddings`**

| Columna | Tipo | Reglas |
|---|---|---|
| `imagen_id` | `uuid` | FK `imagenes` (`ON DELETE CASCADE`) |
| `version_vector` | `text` | p. ej. `dinov2-vitb14/pp-v1` (definido por embeddings, §5.3 de su documento) |
| `vector` | `vector(768)` | normalizado L2 |
| `creado_en` | `timestamptz` | |
| PK | (`imagen_id`, `version_vector`) | |

Índice por versión activa (parcial):
```sql
CREATE INDEX embeddings_hnsw_dinov2_vitb14_pp_v1 ON embeddings
  USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)
  WHERE version_vector = 'dinov2-vitb14/pp-v1';
```
Toda consulta vectorial filtra por la misma `version_vector` para usar el índice. El valor se escribe **como literal**
en
la consulta (sale de `EMBEDDING_VERSION_VECTOR`, nunca de la petición): con un parámetro, las sentencias preparadas de
`asyncpg` pueden pasar a un plan genérico que ignora el índice parcial. Una versión nueva del modelo llega
con su propia migración (índice parcial nuevo) y se activa cambiando `EMBEDDING_VERSION_VECTOR` (§5.10).

**`eventos_localizacion`** (anónimo, retención 180 días)

`id bigserial` · `creado_en` · `origen` (`escaneo`, `frame`) · `resultado` (`ok`, `sin_coincidencias`, `error`) ·
`nivel` · `confianza real` · `lat`, `lng` (redondeadas a 5 decimales, ~1 m) · `fotos_usadas`,
`fotos_con_coincidencia smallint` · `latencia_ms integer` · `version_vector` · `app_version`.
Sin IP, sin identificador de dispositivo, sin fotos.

**`auditoria`**

`id bigserial` · `creado_en` · `actor_id uuid` (nulo en logins fallidos) · `accion text` (`usuario.login`,
`video.renombrar`, `video.eliminar`, `imagen.editar`, `imagen.eliminar`, `imagen.reprocesar`, `lugar.crear`,
`lugar.editar`, `lugar.eliminar`, `alerta.upsert`, `alerta.eliminar`) · `entidad text` · `entidad_id text` ·
`detalle jsonb` (sin secretos).

### 5.8 Mensajes de las colas

Entrega «al menos una vez»: todo consumidor es idempotente. Colas, visibilidad y DLQ: infra §5.6.

**Cola `ingesta`** — dos tipos de mensaje:

1. **Evento de S3** (lo genera S3; formato estándar de notificaciones de S3, versión 2.x):
```json
{ "Records": [ { "eventName": "ObjectCreated:Put",
  "s3": { "bucket": { "name": "campus-locator-dev-dataset-648617469176" },
          "object": { "key": "dataset/9c1d…/a91f….jpg", "size": 345678, "eTag": "…" } } } ] }
```
   - La clave viene codificada como URL: decodificar (`unquote_plus`) antes de usarla.
   - Un mensaje puede traer varios `Records`; se procesan uno a uno.
   - Al configurar la notificación S3 envía `{"Service": "Amazon S3", "Event": "s3:TestEvent", …}`: se borra sin hacer
     nada.
2. **Re-procesado** (lo envía `api`):
```json
{ "tipo": "reprocesar_imagen", "version": 1, "imagen_id": "a91f…",
  "solicitado_por": "7c1e…", "solicitado_en": "2026-10-23T15:04:05Z" }
```

El `worker` distingue por la presencia de `Records` o de `tipo`. Un mensaje que no encaja en ninguno se registra y se
borra.

**Cola `purga`** (la llena `api`):
```json
{ "tipo": "purgar_video", "version": 1, "video_id": "9c1d…",
  "solicitado_por": "7c1e…", "solicitado_en": "2026-10-23T15:04:05Z" }
```
```json
{ "tipo": "purgar_imagen", "version": 1, "imagen_id": "a91f…", "video_id": "9c1d…",
  "s3_keys": ["dataset/9c1d…/a91f….jpg", "thumbs/9c1d…/a91f….jpg"],
  "solicitado_por": "7c1e…", "solicitado_en": "2026-10-23T15:04:05Z" }
```
- `purgar_video`: borra todos los objetos bajo `dataset/{video_id}/` y `thumbs/{video_id}/`, borra las filas de
  `imagenes` del video y fija `videos.purgado_en`. Repetirlo no hace daño.
- `purgar_imagen`: borra los objetos listados (la fila ya se borró en la petición).
- Un cambio incompatible en un mensaje sube `version`; el `worker` acepta la versión actual y la anterior durante un
  despliegue.

### 5.9 Procesos de la imagen

Una sola imagen (`campus-locator/backend`, `project/Dockerfile`, Python 3.12, usuario sin privilegios). Contiene solo
`src/app/` (copiado como paquete `app`) y `migrations/`; `src/ops/` y `tests/` quedan fuera. El contenedor se llama
`app` (infra §5.1).

| Proceso | Comando | Puerto | Salud |
|---|---|---|---|
| `api` (por defecto, `CMD` de la imagen) | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-server-header` | 8000 | `GET /v1/health` |
| `worker` | `python -m app.worker` | — | proceso vivo; registra un latido cada 60 s |
| `migrate` | `python -m app.cli migrar` | — | código de salida 0 = éxito |
| Verificación de esquema (tarea suelta) | `python -m app.cli verificar-esquema` (compara la base con §5.7; no modifica nada) | — | código de salida 0 = coincide, 1 = difiere (imprime las diferencias) |
| Usuarios (tarea suelta con la definición de `migrate`) | `python -m app.cli crear-usuario --correo X --nombre Y [--rol admin\|user]` (contraseña desde la terminal o `CREAR_USUARIO_PASSWORD`). Si el correo existe, actualiza nombre, rol y contraseña y lo reactiva; imprime `creado` o `actualizado` | — | código 0 = hecho |
| | `python -m app.cli desactivar-usuario --correo X` | — | 0 = desactivado (también si ya lo estaba), 1 = no existe |
| Limpieza de pruebas (tarea suelta con la definición de `worker`) | `python -m app.cli limpiar-validacion [--video ID …]` (§4.5): sin `--video`, todos los videos `validacion-`; con `--video`, solo esos, y se niega (código 1) si alguno no lleva el prefijo. Imprime `LIMPIEZA {"videos": n, "objetos": m}` | — | código 0 = hecho |

Variables que lee: las de infra §5.4 para `api`, `worker` y `migrate`. Ningún otro valor es obligatorio; los
parámetros de §5.10 tienen valor por defecto en `config.py` y pueden sobrescribirse con una variable del mismo nombre
(si se vuelve necesario, se añade antes a infra §5.4).

### 5.10 Parámetros operativos

| Parámetro (`config.py`) | Valor inicial | Notas |
|---|---|---|
| `JWT_TTL_MIN` | 720 (12 h) | |
| `EMBEDDING_VERSION_VECTOR` | `dinov2-vitb14/pp-v1` | Debe coincidir con `GET /v1/info` de embeddings. Se comprueba en la primera llamada tras cada arranque del servicio y cada 10 min (no al arrancar `api`, porque embeddings puede estar apagado); si no coincide, no se usa el servicio y `/v1/health/ready` lo informa |
| `EMBEDDING_TIMEOUT_S` / `EMBEDDING_CONNECT_TIMEOUT_S` | 20 / 3 | Un reintento solo si la conexión fue rechazada |
| `LOC_MAX_FOTOS` / `LOC_MAX_BYTES_FOTO` | 5 / 1 572 864 (1,5 MB) | |
| `LOC_TOP_K` / `LOC_EF_SEARCH` | 10 / 64 | Por foto |
| `LOC_SIM_MIN` / `LOC_SIM_ALTA` | 0,55 / 0,80 | **Iniciales: se calibran en BE-3.2 con el conjunto de evaluación de EMB-3.2** |
| `LOC_RADIO_GRUPO_M` / `LOC_PESO_EXPONENTE` / `LOC_RADIO_MIN_M` | 20 / 4 / 5 | |
| Cortes de nivel | `alta` ≥ 0,70 · `media` ≥ 0,45 · `baja` < 0,45 | Iniciales |
| `LOC_DISPERSION_RUMBO_MAX` | 30° | Para devolver `correccion_rumbo_grados` |
| `LOC_LUGAR_CERCANO_M` / `LOC_REFERENCIAS_M` / `LOC_REFERENCIAS_MAX` | 60 / 150 / 3 | |
| `REC_MAX_FOTOS_VIDEO` / `REC_MAX_LOTE` | 200 / 50 | 200 coincide con `MAX_FOTOS_VIDEO` de la app |
| `REC_MAX_BYTES_FOTO` / `REC_LADO_MIN_PX` | 4 194 304 (4 MB) / 320 | Se valida en el `worker` (una URL PUT no limita tamaño) |
| `PRESIGN_PUT_TTL_S` / `PRESIGN_GET_TTL_S` | 900 / 3600 | |
| `MINIATURA_LADO_PX` / `MINIATURA_CALIDAD` | 320 / 80 | |
| `WORKER_MAX_MENSAJES` / `WORKER_LOTE_EMBEDDING` | 10 / 4 | Embeddings admite hasta 8; se usan 4 para no retrasar la localización |
| `WORKER_LADO_EMBEDDING_PX` | 1024 | Copia reducida que se envía al modelo (el original y la miniatura no cambian) |
| `WORKER_ESPERA_EMBEDDING_S` | 15 | Pausa entre comprobaciones de `/health/ready` |
| `RECONCILIADOR_CADA_MIN` | 10 | Purgas pendientes |
| `ALERTAS_TOMBSTONE_DIAS` / `EVENTOS_RETENCION_DIAS` | 90 / 180 | Limpieza diaria desde `api` |
| `PAGINA_POR_DEFECTO` / `PAGINA_MAX` | 24 / 100 | 24 coincide con `FOTOS_POR_PAGINA` de la Galería |
| `DB_POOL` (api / worker) | 5 + 5 de desborde / 2 | `db.t4g.micro` admite ~100 conexiones |
| Formato de log | JSON por línea: `ts`, `nivel`, `proceso`, `request_id`, `evento`, campos propios | Sin secretos ni URLs firmadas |

### 5.11 Validadores del backend

El contrato común (nombres, argumentos, códigos de salida, informe, reglas de datos de prueba) está en
`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Aquí solo lo propio del backend.

**Entornos**

| Entorno | Qué hay | Qué no se puede validar ahí |
|---|---|---|
| `local` | `project/docker-compose.yml`: PostgreSQL 17 con pgvector (`pgvector/pgvector:pg17`), `api` y `worker` construidos desde `project/`, y la imagen de embeddings si se pasa `EMBEDDING_IMAGEN` | S3 y SQS no se emulan: lo que dependa de ellos solo corre en `dev` |
| `dev` | Lo desplegado en AWS (infra §2) | — |

**Variables que leen**

| Variable | Uso | En `dev`, si falta |
|---|---|---|
| `VALIDACION_API_URL` | URL base con `/v1` | Se arma con el output `api_base_url` de infra |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | Iniciar sesión como admin | Se leen del secreto `campus-locator/dev/admin-inicial` |
| `AWS_PROFILE` | Inspeccionar S3, SQS, logs y lanzar tareas | Obligatoria en `dev` |

**Cómo comprueban lo que no se ve desde fuera**
- La base de datos es privada: las comprobaciones de esquema lanzan una tarea suelta con la definición
  `campus-locator-dev-migrate` y el comando `python -m app.cli verificar-esquema` (§5.9), y leen su código de salida y
  su log.
- Para **leer** la base (auditoría, vectores, `purgado_en`…) lanzan la tarea de validación de infra §5.11
  (`campus-locator-dev-validacion`, `psql -tAc "<consulta>"`) y leen su log. Solo consultas `SELECT`: lo que se escribe
  pasa por la API o por los comandos de §5.9.
- La comprobación de disco de BE-3.2 usa ECS Exec sobre la tarea de `api` (infra §3.4).
- Los mensajes y objetos se comprueban con las APIs de SQS y S3; los logs, con CloudWatch Logs.
- La localización (BE-3.2) usa el conjunto de consulta de `evaluacion/` (infra §5.5) que prepara EMB-3.2.
- Lo que devuelve el índice para una foto concreta (por ejemplo, que un video borrado ya no aparece) se ve con
  `POST /v1/admin/diagnostico/vecinos` (§5.5).

**Datos de prueba**: videos con `ref_cliente` y `nombre` que empiezan por `validacion-` (con coordenadas fuera del
campus, para no mezclarse con el dataset real), lugares cuyo nombre empieza por `validacion-`, alertas cuyo mensaje
empieza por `validacion-`, y un usuario `validacion+user@campus.edu.co` de rol `user` para las pruebas de permisos.

**Limpieza**

| Qué | Cómo se borra |
|---|---|
| Lugares y alertas | Con sus `DELETE` de §5.5 (BE-3.1) |
| Videos de prueba, antes de BE-4.1 | `limpiar-validacion --video <id> …` en una tarea suelta con la definición `campus-locator-dev-worker` (§5.9) |
| Videos de prueba, con BE-4.1 hecho | `DELETE /v1/admin/videos/{id}`; su purga limpia S3 |
| Usuario `validacion+user@campus.edu.co` | Lo crea o reactiva `crear-usuario --rol user` (contraseña aleatoria en `CREAR_USUARIO_PASSWORD`, nunca impresa) y lo desactiva `desactivar-usuario` al terminar, ambos en una tarea suelta de `migrate`. La fila queda inactiva entre ejecuciones |

Al empezar, cada validador que crea videos borra los `validacion-` que haya dejado una ejecución interrumpida
(`limpiar-validacion` sin `--video`, o los `DELETE` si BE-4.1 está hecho). Las filas de `auditoria` que generan las
pruebas se conservan (son registro) y las de `eventos_localizacion` caducan a los `EVENTOS_RETENCION_DIAS` (§5.10).

---

## 6. Decisiones de diseño (ADR)

**ADR-BE-01 — Pila: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 asíncrono, asyncpg, Alembic, uv (aceptada).**
Mismo lenguaje que el servicio de embeddings; los esquemas Pydantic son el contrato ejecutable de §5 y generan el
OpenAPI para revisión.

**ADR-BE-02 — API versionada en `/v1`, en español, `snake_case` y enumerados en minúsculas (aceptada).**
Coherente con el resto del proyecto. La app convierte los enumerados a sus `enum` de Kotlin con `uppercase()`.

**ADR-BE-03 — JWT propio HS256, 12 h, sin *refresh*, roles `user`/`admin` (aceptada).** Resuelve la decisión abierta
11 del frontend. Cognito añade costo de integración sin beneficio para un solo tipo de cuenta administrada; API
Gateway HTTP solo valida JWT de emisores OIDC, así que la validación vive en FastAPI. *Consecuencia:* revocar un token
exige desactivar al usuario (se comprueba en cada petición de admin).

**ADR-BE-04 — Subida directa a S3 con URL prefirmada PUT e ingesta asíncrona (aceptada).**
Evita el límite de 10 MB y 30 s de API Gateway y no ocupa a `api`. *Consecuencia:* una URL PUT no limita el tamaño;
lo valida el `worker` (riesgo R4).

**ADR-BE-05 — El `worker` vive en el backend (aceptada).**
El servicio de embeddings queda sin estado, sin base de datos y sin permisos de AWS: solo convierte píxeles en
vectores. Se mantiene la regla del README: el backend es el único que habla con embeddings, base y almacenamiento.

**ADR-BE-06 — Las fotos de `/v1/localize` se descartan tras responder (aceptada).** Resuelve la decisión abierta 7 del
frontend. Solo queda un evento anónimo con posición redondeada, sin identificadores. *Consecuencia:* no se pueden usar
esas fotos para mejorar el dataset; si se quisiera, haría falta consentimiento explícito y una decisión nueva.

**ADR-BE-07 — Borrado lógico, retiro inmediato de vectores, purga asíncrona y auditoría (aceptada).** Resuelve la
decisión abierta 10 del frontend: el borrado es definitivo (sin papelera), cualquier admin puede borrar cualquier
video, y queda quién y cuándo. Los vectores se borran en la misma transacción para que los resultados de ubicación
cambien de inmediato; lo pesado (S3) va a la cola.

**ADR-BE-08 — Localización v1 por vecinos más cercanos + agrupación geográfica (aceptada, revisable).**
Simple, explicable y sin entrenamiento. No usa verificación geométrica (p. ej. emparejar puntos locales); se
reevaluará con los resultados de EMB-3.2. Los parámetros son iniciales y se calibran con datos reales.

**ADR-BE-09 — Vectores en tabla propia con `version_vector` e índice HNSW parcial por versión (aceptada).**
Permite indexar con un modelo o preprocesamiento nuevo en paralelo y cambiar de versión sin tiempo fuera de servicio.

**ADR-BE-10 — Alertas con id del cliente, `PUT` idempotente, *tombstones* y sincronización por diferencias
(aceptada).** Encaja con el editor «local primero» de la app (7.8) y con la caché sin conexión del flujo público (2.5).

**ADR-BE-11 — Cálculo de rutas diferido a Fase 5 (aceptada).** Decisión abierta 2 del frontend: el grafo de caminos
no existe todavía. `GET /v1/route` queda reservado.

**ADR-BE-12 — Rumbo en norte verdadero, [0, 360), en todos los contratos (aceptada).**
El PDR de la app ya usa norte verdadero; el escaneo 360° hoy entrega acimut magnético en (−180, 180]. Unificar en el
contrato obliga a convertir en un solo sitio (la app) y permite comparar rumbos del dataset con los de la consulta.

---

## 7. Riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | La precisión de ubicación no alcanza (dataset escaso, cambios de luz, lugares parecidos) | Alta | Alto | Conjunto de evaluación (EMB-3.2), calibrar umbrales, confianza honesta (`baja` → repetir), cobertura visible en el panel |
| R2 | `/v1/localize` supera 5 s en CPU | Media | Medio | Medir en EMB-2.1; fotos de 1024 px; 2 vCPU o ONNX/cuantización si hace falta |
| R3 | La ingesta retrasa la localización (un solo servicio de embeddings, que no interrumpe un lote en curso) | Media | Medio | Prioridad `alta` para localización (embeddings §5.2); lotes de 4 imágenes reducidas en el `worker` |
| R4 | Una URL PUT permite subir archivos enormes | Baja | Bajo | URL de 15 min ligada a una clave; el `worker` rechaza > 4 MB y la purga los borra |
| R5 | Rumbos de fuentes distintas (magnético vs. verdadero) | Alta | Medio | ADR-BE-12; lote del frontend para convertir en el escaneo |
| R6 | Eventos de S3 duplicados o fuera de orden | Media | Bajo | Idempotencia por imagen y ETag |
| R7 | Fuerza bruta contra el login | Baja | Alto | *Throttling* de API Gateway, argon2id, auditoría de intentos, alarma de 5xx |
| R8 | Reloj del teléfono desajustado (`capturada_en`) | Media | Bajo | El servidor guarda `creado_en` propio; `capturada_en` solo informa |
| R9 | `db.t4g.micro` se queda corto (memoria del índice, conexiones) | Baja | Medio | Pools pequeños; ver infra R4 |
| R10 | Formatos de error distintos cuando responde API Gateway | Alta | Bajo | §5.1 lo documenta; la app decide por código HTTP |
