# ARCHITECTURE — Servicio de embeddings (`SERVICE_EMBEDDING`)

| Campo | Valor |
|---|---|
| Versión del documento | **0.2.0** (historia en [`CHANGELOG.md`](./CHANGELOG.md)) |
| Fecha | 2026-10-23 |
| Estado | Diseño propuesto. **Aún no hay código** |
| Qué se construye y en qué orden | [`PLAN.md`](./PLAN.md) · cómo se comprueba cada lote: [`validation/`](./validation/) |

Servicio HTTP interno que convierte fotos en **vectores de 768 dimensiones** con **DINOv2 ViT-B/14** sobre CPU. No
guarda nada, no conoce la base de datos ni S3, y solo lo llaman los procesos `api` y `worker` del backend.

Su **§5 es la única fuente de verdad** de: la API interna, el modelo y su revisión, el preprocesamiento, el
identificador de versión del vector (`version_vector`), el formato del vector, la imagen de contenedor y los
parámetros operativos del servicio.

---

## 1. Propósito y alcance

### 1.1 Qué cubre
- Cargar el modelo una vez, preprocesar imágenes y devolver vectores normalizados.
- Atender primero las peticiones de localización (interactivas) frente a las de ingesta (en segundo plano).
- Herramientas de evaluación de la calidad de recuperación (EMB-3.2) y medición de rendimiento (EMB-3.1).

### 1.2 Qué no cubre
- Búsqueda de vecinos, agrupación y cálculo de posición: backend (`BACKEND_FASTAPI/docs/ARCHITECTURE.md` §4.10).
- Almacenamiento de vectores: pgvector, esquema del backend (§5.7 de su documento).
- Infraestructura (tamaño de tarea, DNS interno, horario): `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md`.

### 1.3 Regla de contratos
Este documento define lo que el servicio **expone**. Lo que consume se enlaza:

| Consume | Definido en |
|---|---|
| Variables de entorno `TORCH_NUM_THREADS`, `LOG_LEVEL`, `APP_ENV` | Infra §5.4 |
| Nombre DNS `embedding.campus-locator.local:8080`, grupo de seguridad, *health check* del contenedor | Infra §5.7 |
| Contrato de despliegue (imagen `linux/amd64`, etiqueta = SHA) | Infra §5.9 |

---

## 2. Contexto en el sistema

```
  api    ──POST /v1/embed (X-Prioridad: alta, 1–5 fotos)──┐
                                                           ▼
                                        ┌──────────────────── embedding ────────────────────┐
                                        │ FastAPI ─► cola con prioridad ─► 1 hilo de        │
                                        │            (alta antes que baja)  inferencia      │
                                        │                                   DINOv2 ViT-B/14 │
                                        └───────────────────────────────────────────────────┘
                                                           ▲
  worker ──POST /v1/embed (X-Prioridad: baja, hasta 8)─────┘
```

- **Un único modelo cargado** y **una única inferencia a la vez**: con el vCPU de la tarea (infra §3.4), ejecutar dos
  en paralelo solo las hace más lentas a ambas.
- Llamado por `api` (`POST /v1/localize`) y por `worker` (ingesta). El backend comprueba que `version_vector`
  coincide con la que espera en la primera llamada tras cada arranque del servicio y cada 10 min (backend §5.10).

---

## 3. Arquitectura en AWS (vista del servicio)

- Servicio ECS `embedding` en Fargate; tamaño de tarea, red y DNS interno en infra §3.4 y §5.7. Escucha en el puerto
  de §5.5 y no recibe tráfico desde internet.
- En `dev` solo está encendido en el horario de infra §5.10 (ADR-INF-11).
- Arranque: descarga de la imagen (~2 GB) + carga del modelo + calentamiento; el *health check* del contenedor tiene
  un *start period* de 180 s.
- Sin rol de tarea con permisos: el servicio no llama a ningún servicio de AWS.
- Logs JSON a `/campus-locator/dev/embedding`.

---

## 4. Componentes y funcionamiento (por lote)

### 4.1 Estructura del código

```
SERVICE_EMBEDDING/
├── docs/
│   ├── ARCHITECTURE.md, PLAN.md, CHANGELOG.md
│   └── validation/               validation-<fase>-<n>.md: cómo se comprueba cada lote (§5.8)
└── project/                      todo el código
    ├── src/
    │   ├── app/
    │   │   ├── main.py           FastAPI: rutas, arranque (carga + calentamiento), manejador de errores
    │   │   ├── config.py         Parámetros de §5.7 (pydantic-settings)
    │   │   ├── modelo.py         Carga de DINOv2 desde MODELO_DIR, inferencia por lotes, normalización L2
    │   │   ├── preproceso.py     Pipeline pp-v1 (función pura: bytes → tensor)
    │   │   └── planificador.py   Cola con prioridad y el hilo único de inferencia
    │   └── ops/                  validate<fase><n>.py y comun.py: validadores de los lotes EMB-x.y (§5.8)
    ├── tools/
    │   ├── descargar_modelo.py   Se ejecuta en el build: baja la revisión fija a /opt/modelo
    │   ├── benchmark.py          EMB-3.1: latencia por tamaño de lote (va dentro de la imagen, §5.8)
    │   └── evaluacion/           EMB-3.2: recuperación sobre un conjunto etiquetado
    ├── tests/                    preproceso, vectores dorados (golden/), contrato HTTP
    ├── Dockerfile
    └── pyproject.toml            uv; ruff; pytest; grupo `ops` para los validadores
```

### 4.2 EMB-1.1 — Servicio base e imagen
- El `Dockerfile` instala PyTorch para CPU desde el índice de ruedas de CPU de PyTorch (evita las dependencias de
  CUDA y ahorra más de 1 GB) y `transformers`, y **descarga los pesos durante el build** a `/opt/modelo` con la
  revisión fija de §5.3. En ejecución se activa `HF_HUB_OFFLINE=1`: el servicio no sale a internet para nada.
- Al arrancar: carga el modelo en modo evaluación, fija los hilos (`TORCH_NUM_THREADS`), ejecuta dos inferencias de
  calentamiento (lote 1 y lote 8) y solo entonces `GET /health/ready` responde 200.
- `GET /v1/info` publica la versión del vector para que el backend la compruebe.

### 4.3 EMB-2.1 — Vectorización por lotes
1. `POST /v1/embed` recibe 1–8 imágenes y valida tipo y tamaño antes de encolar.
2. La petición entra en una **cola con prioridad**: `alta` (localización) antes que `baja` (ingesta); dentro de cada
   prioridad, por orden de llegada. La prioridad no interrumpe un lote que ya se está calculando: una petición `alta`
   espera como máximo a que termine el lote en curso (por eso el `worker` envía lotes pequeños, backend §5.10). Si la
   cola supera `COLA_MAX_IMAGENES`, responde `503 SATURADO` con `Retry-After`
   (el `worker` reintenta; la localización casi nunca llega a ese punto porque pasa primero).
3. El hilo de inferencia toma una petición, aplica el preprocesamiento pp-v1 a cada imagen, corre **un solo lote** con
   todas las imágenes de esa petición y normaliza cada vector.
4. Responde los vectores en el mismo orden de entrada, con los tiempos de cola e inferencia.

Si una sola imagen no se puede decodificar, se rechaza **la petición completa** con `400 IMAGEN_INVALIDA` y el índice
de la imagen: el que llama decide si reintenta sin ella (el `worker` marca esa imagen en `error` y reintenta el
resto).

### 4.4 EMB-3.1 — Rendimiento en CPU
`project/tools/benchmark.py` mide p50 y p95 para lotes de 1, 5 y 8 imágenes en una tarea igual a la de `dev`. Objetivo:
lote de
5 en p95 ≤ 3 s, para que `POST /v1/localize` quede en ≤ 5 s. Si no se alcanza, en este orden: ajustar hilos;
exportar a ONNX Runtime; cuantizar a int8; subir la tarea a 2 vCPU (afecta el presupuesto, infra §3.10). Exportar o
cuantizar cambia los vectores: exigiría una `version_vector` nueva (ADR-EMB-08).

### 4.5 EMB-3.2 — Conjunto de evaluación y calibración
- Conjunto: fotos de consulta tomadas en puntos conocidos del campus (no usadas en el dataset), con su coordenada.
- Métricas: *recall@1* y *recall@5* «a 15 m» (algún vecino recuperado está a ≤ 15 m del punto real), y la distribución
  de similitudes entre «mismo lugar» y «otro lugar».
- Salida: valores recomendados de `LOC_SIM_MIN`, `LOC_SIM_ALTA` y cortes de nivel para el backend (BE-3.2), y la
  comparación de pp-v1 con variantes (sin recorte central, resolución mayor, media de *tokens* de parches en lugar del
  CLS). Las variantes no se despliegan: si alguna gana, se abre EMB-5.1.

### 4.6 EMB-5.1 — Nueva versión del vector (diferido)
Procedimiento previsto para cambiar de modelo o preprocesamiento sin dejar de ubicar:
1. Nueva `version_vector` (§5.3) y vectores dorados nuevos.
2. Backend: migración con el índice parcial de la nueva versión (backend ADR-BE-09).
3. Re-indexado: el `worker` re-procesa todas las imágenes con un servicio temporal de la nueva versión (el servicio
   expone **una sola** versión a la vez).
4. Cambio de `EMBEDDING_VERSION_VECTOR` en el backend y despliegue de la nueva versión del servicio.
5. Borrado de los vectores e índice de la versión anterior.

---

## 5. Interfaces (contratos)

> **Única fuente de verdad** de lo que expone este servicio. Cambiar algo aquí sube la versión de este documento y
> exige entrada en `CHANGELOG.md`. Cambiar el modelo, la revisión o el preprocesamiento exige además una
> `version_vector` nueva.

### 5.1 Convenciones

| Tema | Regla |
|---|---|
| URL base | `EMBEDDING_URL` (valor en infra §5.4). HTTP sin TLS: tráfico privado dentro de la VPC |
| Autenticación | Ninguna. El acceso lo limita el grupo de seguridad (solo `api` y `worker`) |
| Formato | JSON UTF-8, `snake_case`, en español |
| Errores | `{"error": {"codigo": "…", "mensaje": "…", "detalle": {…} \| null}}` (mismo formato que el backend) |
| Correlación | Respeta y devuelve `X-Request-Id` |

### 5.2 Endpoints

#### `GET /health`
`200` → `{"estado": "ok"}` mientras el proceso viva (aunque el modelo esté cargando).

#### `GET /health/ready`
`200` → `{"estado": "listo"}` con el modelo cargado y calentado. `503` → `{"estado": "cargando"}` antes. Lo usan el
*health check* del contenedor (infra §5.7), `/v1/health/ready` del backend y el `worker` antes de tomar mensajes.

#### `GET /v1/info`
`200`:
```json
{
  "servicio": "campus-locator-embedding",
  "version": "0.1.0",
  "commit": "a1b2c3d",
  "modelo": "facebook/dinov2-base",
  "revision": "<SHA del commit del repositorio de Hugging Face, fijado en EMB-1.1>",
  "arquitectura": "ViT-B/14",
  "preprocesamiento": "pp-v1",
  "version_vector": "dinov2-vitb14/pp-v1",
  "dim": 768,
  "normalizacion": "l2",
  "metrica": "coseno",
  "lote_max": 8,
  "dispositivo": "cpu"
}
```

#### `POST /v1/embed`
- `multipart/form-data` con 1 a `LOTE_MAX` (8) partes llamadas `imagenes`, de tipo `image/jpeg` o `image/png`, cada
  una ≤ 4 MB y la petición completa ≤ 16 MB.
- Encabezado opcional `X-Prioridad: alta | baja` (por defecto `baja`). `api` envía `alta`; `worker`, `baja`.

`200`:
```json
{
  "version_vector": "dinov2-vitb14/pp-v1",
  "dim": 768,
  "vectores": [[0.0123, -0.0456, …], [ … ]],
  "tiempos_ms": { "cola": 12, "inferencia": 1840 }
}
```
- `vectores[i]` corresponde a la `i`-ésima parte `imagenes`, en el orden recibido.
- Cada vector tiene exactamente `dim` números (float32 serializados como números JSON) y norma L2 = 1 (±1e-4).

### 5.3 Modelo, preprocesamiento y `version_vector`

| Elemento | Valor en `pp-v1` |
|---|---|
| Modelo | `facebook/dinov2-base` (DINOv2 ViT-B/14, 86 M parámetros, licencia Apache 2.0) en `transformers` (`Dinov2Model`) |
| Revisión | SHA de commit fijo del repositorio en Hugging Face; se elige y anota aquí en EMB-1.1 |
| Precisión | float32, `torch.inference_mode()`, modo evaluación |
| 1. Decodificación | Pillow; orientación EXIF aplicada (`ImageOps.exif_transpose`); convertir a RGB (descarta alfa) |
| 2. Redimensión | Lado **menor** a 256 px, interpolación bicúbica con antialias, manteniendo proporción |
| 3. Recorte | Central de 224 × 224 px (16 × 16 parches de 14 px) |
| 4. Normalización | Escala [0, 1]; media (0,485; 0,456; 0,406); desviación (0,229; 0,224; 0,225) |
| 5. Salida del modelo | *Token* CLS de la última capa tras la *layernorm* final (`pooler_output` de `Dinov2Model`) |
| 6. Normalización del vector | L2 |

**`version_vector`** = `dinov2-vitb14/pp-v1`. Identifica de forma única la combinación modelo + revisión +
preprocesamiento + extracción. Dos vectores solo son comparables si tienen la misma `version_vector`. Cambiar
**cualquiera** de las filas de la tabla (incluida la revisión del modelo o una librería que altere los números más allá
de la tolerancia de §5.4) exige una versión nueva (ADR-EMB-08).

### 5.4 Formato y garantías del vector

- Dimensión 768, float32, norma L2 = 1. Métrica prevista: **coseno**; como están normalizados, coseno = producto
  escalar. En pgvector se guardan como `vector(768)` y se buscan con `vector_cosine_ops` (backend §5.7).
- **Determinismo:** la misma imagen produce el mismo vector en la misma imagen de contenedor, con diferencia máxima
  por componente ≤ 1e-5. Se verifica con **vectores dorados** (`tests/golden/`): cinco imágenes de referencia y sus
  vectores esperados. Si una actualización de dependencias rompe esa tolerancia, no se despliega sin versión nueva.
- **Independencia del tamaño de lote:** el vector de una imagen no depende de con qué otras imágenes viajó, con la
  misma tolerancia de 1e-5 (la aritmética float32 en CPU puede variar mínimamente con el tamaño del lote).

### 5.5 Imagen de contenedor y proceso

| Elemento | Valor |
|---|---|
| Repositorio ECR | `campus-locator/embedding` (infra §5.1) |
| Base | `python:3.12-slim`, usuario sin privilegios, contenedor `app` |
| Comando (`CMD`) | `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1 --no-server-header` |
| Puerto | `8080` |
| Pesos | En la imagen, `/opt/modelo` (descargados en el build) |
| Contenido | `src/app/` (como paquete `app`) y `tools/benchmark.py`; `src/ops/`, `tests/` y `tools/evaluacion/` quedan fuera |
| Variables fijadas en el `Dockerfile` | `MODELO_DIR=/opt/modelo`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` (la aplicación además aplica `TORCH_NUM_THREADS` a PyTorch y a OpenMP al arrancar) |
| Variables que inyecta la infraestructura | `TORCH_NUM_THREADS`, `LOG_LEVEL`, `APP_ENV` (infra §5.4) |
| Tamaño esperado | ~2 GB (PyTorch CPU + transformers + pesos de ~350 MB) |
| Memoria en ejecución | ~1,5 GB en reposo; la tarea tiene 3 GB para lotes de 8 |

### 5.6 Códigos de error

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 400 | `SOLICITUD_INVALIDA` | Sin partes `imagenes` o multipart mal formado |
| 400 | `IMAGEN_INVALIDA` | Una imagen no se pudo decodificar o mide menos de 64 px de lado; `detalle.indice` = posición |
| 413 | `LOTE_DEMASIADO_GRANDE` | Más de 8 imágenes, una de más de 4 MB o una petición de más de 16 MB |
| 415 | `TIPO_NO_SOPORTADO` | Tipo distinto de `image/jpeg` o `image/png` |
| 503 | `NO_LISTO` | El modelo aún carga |
| 503 | `SATURADO` | Cola por encima de `COLA_MAX_IMAGENES`; incluye `Retry-After` en segundos |
| 500 | `ERROR_INTERNO` | Fallo no previsto (incluida falta de memoria) |

### 5.7 Parámetros operativos

| Parámetro | Valor | Notas |
|---|---|---|
| `LOTE_MAX` | 8 | El `worker` del backend envía lotes de 4 (backend §5.10) |
| `BYTES_MAX_IMAGEN` / `BYTES_MAX_PETICION` | 4 MB / 16 MB | |
| `LADO_MIN_PX` | 64 | Antes del preprocesamiento |
| `COLA_MAX_IMAGENES` | 40 | Imágenes esperando, sumando todas las peticiones; no cuenta el lote que se está calculando |
| `RETRY_AFTER_S` | 5 | En `503 SATURADO` |
| Hilos de PyTorch | `TORCH_NUM_THREADS` (valor en infra §5.4) | Igual a los vCPU de la tarea |
| Latencia objetivo | lote de 5: p95 ≤ 3 s; lote de 1: p95 ≤ 1 s | **A medir en EMB-3.1**; aún sin datos |
| Formato de log | JSON por línea: `ts`, `nivel`, `request_id`, `prioridad`, `n_imagenes`, `cola_ms`, `inferencia_ms` | Nunca bytes de imagen |

### 5.8 Validadores del servicio

El contrato común (nombres, argumentos, códigos de salida, informe, reglas de datos de prueba) está en
`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Aquí solo lo propio de este servicio.

**Entornos**

| Entorno | Cómo llega el validador al servicio | Para qué |
|---|---|---|
| `local` | Arranca la **misma imagen** que se despliega (`EMBEDDING_IMAGEN`: etiqueta de ECR o construcción local de `project/`) con `docker run -p 8080:8080` y llama a `http://localhost:8080` | Comprobaciones funcionales de la API, vectores dorados, prioridad, arranque sin red (`--network none`) |
| `dev` | El servicio es privado: el validador lanza **tareas sueltas** con la definición `campus-locator-dev-embedding` (comando sobrescrito) o consulta ECS (`describe-tasks`, eventos del servicio) y CloudWatch Logs; además puede comprobar `embedding: ok` en `GET /v1/health/ready` del backend | Tiempos de arranque reales, rendimiento en el tamaño de tarea de `dev`, imagen desplegada |

**Variables que leen**: `EMBEDDING_IMAGEN` (en `local`), `AWS_PROFILE` (en `dev`) y, para EMB-3.2,
`VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD` (las mismas del backend, su §5.11). Las
imágenes de referencia de los vectores dorados están en `project/tests/golden/`.

**Lo que la imagen incluye para los validadores**: `tools/benchmark.py` va dentro de la imagen (en `/srv/tools/`) para
poder ejecutarlo como tarea suelta en `dev` con el comando `python tools/benchmark.py --salida json`; el resultado
(formato en §5.9) se lee del log `/campus-locator/dev/embedding`. `tools/evaluacion/` no va en la imagen: se ejecuta en
la máquina de quien valida, lee el conjunto de `evaluacion/` del bucket (infra §5.5) y obtiene los vecinos del dataset
con el endpoint de diagnóstico del backend (§5.9).

**Datos de prueba**: imágenes sintéticas generadas por el propio validador y las cinco imágenes de
`project/tests/golden/`; el servicio no guarda nada, así que no hay limpieza más allá de detener las tareas sueltas.

### 5.9 Formatos de las herramientas y del conjunto de evaluación

**Salida de `tools/benchmark.py --salida json`**: una sola línea en la salida estándar (y por tanto en el log),
precedida de `BENCHMARK_JSON ` para poder encontrarla:
```json
{ "version_vector": "dinov2-vitb14/pp-v1", "commit": "a1b2c3d", "hilos": 1, "vcpu": 1, "memoria_mb": 3072,
  "resultados": [ { "lote": 1, "repeticiones": 30, "p50_ms": 410, "p95_ms": 520 },
                  { "lote": 5, "repeticiones": 20, "p50_ms": 1900, "p95_ms": 2300 },
                  { "lote": 8, "repeticiones": 10, "p50_ms": 3000, "p95_ms": 3400 } ] }
```
(Los números del ejemplo son ilustrativos, no medidos.) Cada repetición usa imágenes sintéticas de 1024 px, mide desde
que la petición entra en la cola hasta que sale la respuesta y descarta las 3 primeras como calentamiento.

**Conjunto de evaluación** (EMB-3.2), en el bucket del dataset bajo `evaluacion/<version_conjunto>/` (infra §5.5):
```
evaluacion/2026-11a/
├── puntos.json
├── fotos/<punto>/<n>.jpg
└── informes/<version_vector>-<AAAAMMDD>.json   (y .md, el mismo informe para leer)
```
En el nombre del informe, la `/` de la `version_vector` se escribe `_` (`dinov2-vitb14_pp-v1-20261105.json`).
`puntos.json`:
```json
{ "version_conjunto": "2026-11a", "creado_en": "2026-11-05T14:00:00Z",
  "puntos": [ { "id": "P01", "lat": 6.200104, "lng": -75.578612, "descripcion": "Entrada de la biblioteca" } ],
  "fotos": [ { "archivo": "fotos/P01/1.jpg", "punto": "P01", "rumbo": 90.0, "capturada_en": "2026-11-05T14:02:10Z", "hora": "manana" } ] }
```
`rumbo` en norte verdadero [0, 360) o `null`; `hora` ∈ {`manana`, `tarde`, `noche`}. Las fotos no se usan nunca en
el dataset. El conjunto incluye además al menos un punto lejos del dataset (> 150 m de toda imagen): sus fotos no
entran en el *recall* y sirven para comprobar `sin_coincidencias` (BE-3.2 C5).

**Informe de evaluación** (`informes/<version_vector>-<AAAAMMDD>.json`):
```json
{ "version_conjunto": "2026-11a", "version_vector": "dinov2-vitb14/pp-v1", "fotos": 50, "puntos": 10,
  "recall_1_15m": 0.0, "recall_5_15m": 0.0,
  "similitud": { "mismo_lugar": { "p10": 0.0, "p50": 0.0, "p90": 0.0 }, "otro_lugar": { "p10": 0.0, "p50": 0.0, "p90": 0.0 } },
  "variantes": [ { "nombre": "pp-v1", "recall_1_15m": 0.0, "recall_5_15m": 0.0 } ],
  "recomendado": { "LOC_SIM_MIN": 0.0, "LOC_SIM_ALTA": 0.0, "corte_alta": 0.0, "corte_media": 0.0 } }
```
«Mismo lugar» = vecino a ≤ 15 m del punto real; «otro lugar» = vecino a > 50 m. Los vecinos del dataset se obtienen con
`POST /v1/admin/diagnostico/vecinos` del backend (backend §5.5), con `k = 5`. `variantes` incluye siempre `pp-v1`
(los mismos números de arriba); una variante de preprocesamiento distinta se evalúa sin tocar `dev`: la herramienta
descarga las imágenes del dataset con las URL de `GET /v1/admin/images`, las vectoriza con la variante en un
contenedor local y busca los vecinos por fuerza bruta.

---

## 6. Decisiones de diseño (ADR)

**ADR-EMB-01 — DINOv2 ViT-B/14, vectores de 768 dimensiones (aceptada).**
Elegido por el equipo. ViT-S/14 (384) es más rápido pero menos discriminativo; ViT-L/14 (1024) triplica el costo en
CPU. DINOv2 es autosupervisado y sus descriptores globales funcionan bien para recuperar imágenes del mismo lugar sin
entrenamiento adicional. Licencia Apache 2.0.

**ADR-EMB-02 — PyTorch CPU + `transformers` (aceptada).**
Lo más simple de mantener. ONNX Runtime y cuantización quedan como palancas de rendimiento (EMB-3.1), sabiendo que
cambian los vectores.

**ADR-EMB-03 — Descriptor = *token* CLS normalizado, métrica coseno (aceptada, revisable en EMB-3.2).**
Estándar, compacto y directamente indexable en pgvector. La media de *tokens* de parches o agregaciones tipo GeM se
comparan en EMB-3.2.

**ADR-EMB-04 — Preprocesamiento estándar de ImageNet: lado menor 256, recorte central 224 (aceptada, revisable).**
Es el preprocesamiento con el que se publicó el modelo. *Consecuencia:* en fotos verticales del teléfono se pierde
cerca de un tercio de la altura; EMB-3.2 mide si conviene no recortar o usar más resolución.

**ADR-EMB-05 — Pesos dentro de la imagen, revisión fija, sin red en ejecución (aceptada).**
Arranques reproducibles y sin depender de Hugging Face en producción. *Consecuencia:* imagen de ~2 GB y arranque más
lento (riesgo R3).

**ADR-EMB-06 — Servicio sin estado, sin acceso a AWS ni a la base, sin autenticación (aceptada).**
Minimiza su superficie: solo convierte píxeles en números. La red privada y el grupo de seguridad limitan quién lo
llama.

**ADR-EMB-07 — Cola con prioridad y una sola inferencia a la vez (aceptada).**
Con 1 vCPU la concurrencia no aumenta el rendimiento; la prioridad protege la latencia de la localización frente a la
ingesta.

**ADR-EMB-08 — `version_vector` explícita y cambios nunca silenciosos (aceptada).**
Mezclar vectores de versiones distintas degrada la búsqueda sin dar errores. Cualquier cambio que altere los números
produce una versión nueva y un re-indexado (procedimiento de §4.6).

---

## 7. Riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | Latencia en CPU por encima del objetivo | Media | Medio | EMB-3.1; palancas de §4.4 |
| R2 | Calidad de recuperación insuficiente (luz, oclusiones, recorte central, lugares parecidos) | Media | Alto | EMB-3.2; EMB-5.1 si una variante gana |
| R3 | Imagen grande: arranques de 1–3 min | Alta | Bajo | *Start period* de 180 s; el `worker` espera a `/health/ready`; horario de `dev` |
| R4 | Una actualización de librerías cambia los vectores sin avisar | Media | Alto | Versiones fijadas en `uv.lock`; vectores dorados en CI |
| R5 | Ingesta masiva satura el servicio | Media | Bajo | Prioridad; `503 SATURADO`; el `worker` reintenta |
| R6 | Falta de memoria con lotes grandes | Baja | Medio | `LOTE_MAX = 8`; 3 GB de tarea; medir en EMB-3.1 |
| R7 | La revisión fijada desaparece de Hugging Face | Baja | Medio | Las imágenes ya publicadas en ECR conservan los pesos; guardar una copia de los pesos fuera de Hugging Face si se vuelve crítico |
