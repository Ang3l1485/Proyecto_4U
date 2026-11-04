# Validación 2-1 — EMB-2.1 Vectorización por lotes

| Campo | Valor |
|---|---|
| Lote | `EMB-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `local` (**cierra el lote**, con `EMBEDDING_IMAGEN` = la imagen que `embedding.yml` publicó en ECR para el commit que se cierra). `dev` no aplica: el servicio es privado y §5.8 reserva `dev` para arranque y rendimiento |
| Criterios | Automáticos: C1, C2, C3, C4, C5 (C5a, C5b, C5c) · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.8.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Docker disponible y puerto 8080 libre | `docker info` con código 0; una conexión a `localhost:8080` es rechazada |
| P2 | `EMBEDDING_IMAGEN` definida y de plataforma `linux/amd64` (infra §5.9) | `docker pull` (si es de ECR, tras `aws ecr get-login-password` con `AWS_PROFILE`) y `docker image inspect --format '{{.Os}}/{{.Architecture}}'` = `linux/amd64`. Sin variable: código 3 (§5.11) |
| P3 | `EMB-1.1` en «Hecho»: la imagen arranca, queda lista y publica su `version_vector` | `docker run -d --name validacion-emb21 -p 8080:8080 -e TORCH_NUM_THREADS=1 $EMBEDDING_IMAGEN`; `GET http://localhost:8080/health/ready` = 200 `{"estado": "listo"}` antes de 180 s; `GET /v1/info` → `version_vector = dinov2-vitb14/pp-v1` y `lote_max = 8` |

## 2. Comprobaciones automáticas

Todas las peticiones van a `POST http://localhost:8080/v1/embed` en `multipart/form-data` con partes `imagenes`, llevan
`X-Request-Id: validacion-emb21-<n>` y, salvo que se indique, no envían `X-Prioridad` (= `baja`).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Envía sola cada una de las cinco imágenes de `project/tests/golden/` (`image/jpeg` o `image/png` según el archivo) y compara la respuesta con su vector esperado del mismo directorio | Las cinco responden `200` con `version_vector = dinov2-vitb14/pp-v1`, `dim = 768` y 768 componentes, y la diferencia máxima por componente es ≤ 1e-5 |
| C2 | Una petición con 8 partes (las 5 doradas y 3 sintéticas JPEG de 640 × 480 con semilla fija) y cada una de esas 8 imágenes sola | Para las 8, `vectores[i]` del lote y el vector de la imagen enviada sola difieren ≤ 1e-5 por componente |
| C3 | Una petición con 4 partes válidas salvo la tercera: `image/jpeg` con bytes no decodificables (JPEG truncado) | `400`, `error.codigo = IMAGEN_INVALIDA` y `error.detalle.indice = 2` |
| C4 | Envía a la vez 4 peticiones `baja` de 8 imágenes sintéticas (33 imágenes con la `alta`, por debajo de `COLA_MAX_IMAGENES` = 40 aunque cuente el lote en curso) y, 1 s después, una con `X-Prioridad: alta` y 1 imagen. Para cada petición calcula su salida de la cola = instante de envío + `tiempos_ms.cola` | (a) al menos 2 `baja` salen de la cola después del envío de la `alta` (seguían esperando); (b) la `alta` sale antes que todas ellas; (c) su `tiempos_ms.cola` ≤ `tiempos_ms.inferencia` de la `baja` en curso + 500 ms (solo espera ese lote, §4.3) |
| C5a | Tres peticiones: 9 partes; 1 parte de ruido sintético de más de 4 MB; 5 partes de ~3,5 MB (más de 16 MB en total) | Las tres responden `413` con `error.codigo = LOTE_DEMASIADO_GRANDE` |
| C5b | Una petición con 1 parte `image/gif` sintética | `415` con `error.codigo = TIPO_NO_SOPORTADO` |
| C5c | Envía a la vez 8 peticiones `baja` de 8 imágenes sintéticas (64 imágenes frente a `COLA_MAX_IMAGENES` = 40) | Al menos una responde `503` con `error.codigo = SATURADO` y encabezado `Retry-After: 5` (`RETRY_AFTER_S`, §5.7); el resto, `200` |

Antes de C4 y de C5c el script espera a que respondan todas las peticiones anteriores, para empezar con la cola vacía.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

El servicio no guarda nada (§5.8). El script usa las cinco imágenes de `project/tests/golden/` e imágenes sintéticas que
genera en memoria con semilla fija (JPEG de 640 × 480, ruido para las de más de 3,5 MB, un GIF para C5b y un JPEG
truncado para C3); no escribe nada en disco. El único recurso es el contenedor `validacion-emb21`: al terminar (también
si algo falló, salvo `--sin-limpieza`) lo borra con `docker rm -f`, y al empezar borra el que haya quedado de una
ejecución anterior con ese nombre.

## 5. Cómo ejecutarlo

```bash
cd SERVICE_EMBEDDING/project
EMBEDDING_IMAGEN=<ecr_embedding_url>:<sha> uv run --group ops python src/ops/validate21.py --entorno local
```

Variables: `EMBEDDING_IMAGEN` (§5.8); `AWS_PROFILE` solo si la imagen es de ECR. Duración aproximada: 5–10 min
(arranque de hasta 3 min y unos 13 lotes de 8 imágenes entre C2, C4 y C5c).
