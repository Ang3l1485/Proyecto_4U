# HU-020 · Resultado de las pruebas automatizadas

**Servicio:** `SERVICE_EMBEDDING` (FastAPI + CLIP `openai/clip-vit-base-patch32`) · **Fecha:** 3 de noviembre de 2026 · **Responsable:** Miguel Ángel García

## Alcance

Pruebas locales con `pytest`, **sin credenciales de AWS ni red**: boto3, psycopg2 y la base de datos se sustituyen,
y una guardia bloquea cualquier conexión externa. Las imágenes se generan en memoria (no se versionan fotos).
No se modificó el código del servicio (`app/`, `Dockerfile`, `ecs/`).

**Entorno:** Windows, Python 3.12.2, pytest 9.2.0, torch 2.15.0+cpu, transformers 5.22.1, fastapi 0.162.0.

## Resultado

| Ejecución | Comando | Resultado | Tiempo |
|---|---|---|---|
| Pruebas rápidas | `python -m pytest -v` | **48 aprobadas**, 0 fallidas | ≈ 6 s |
| CLIP real (opcional) | `python -m pytest -m modelo` | **1 aprobada**, 0 fallidas | ≈ 24 s |

| Escenario HU-020 | Qué se verificó | Pruebas | Estado |
|---|---|---|---|
| 1. Carga al arrancar | `/health` listo / no listo; carga única al arrancar; referencias normalizadas; si falla la base no queda "listo" | 13 | ✅ |
| 2. Predicción | `/predict` devuelve `location`, `point_id`, `similarity` (4 decimales), `matched_ref_image`; elige la mayor similitud; vector CLIP `float32` de norma 1 (512 con el modelo real) | 15 (+1 opcional) | ✅ |
| 3. Errores controlados | 400 si no es imagen, 503 si no está listo, 422 si falta `image` | 4 | ✅ |
| 5. Despliegue reproducible | Mismo modelo en `config.py`, `task_definition.json` y `Dockerfile`; puerto 8080; 2 vCPU / 4 GB | 5 | ✅ |
| 6. Acceso sin contraseñas | Token IAM como contraseña, `sslmode=require`, sin secretos en la definición de tarea, contenedor sin root | 7 | ✅ |
| Base | Importa sin AWS ni red; guardia de red activa | 4 | ✅ |
| **Total** | | **48** | ✅ |

El escenario 4 (validación con `temp/code.py`) no se automatizó porque el script corre todo al importarse.

**Control de calidad de las pruebas:** se introdujeron tres errores a propósito en una copia del código
(`sslmode="disable"`, redondeo a 2 decimales, `argmin` en vez de `argmax`); las pruebas detectaron los tres.

## Observaciones (no bloquean la HU)

- Con `train_embeddings` vacía el servicio no arranca (`np.vstack` sobre una lista vacía). Queda como limitación conocida.
- FastAPI marca `@app.on_event("startup")` como obsoleto; conviene migrar a `lifespan` al pasar a `SERVICE_EMBEDDING/`.
- Las pruebas verifican el contrato del servicio, **no** su precisión con fotos reales del campus: eso corresponde a la HU de evaluación y umbrales.

## Cómo reproducir

```bash
cd SERVICE_EMBEDDING
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -v
```

Detalle por archivo en `tests/README.md`.
