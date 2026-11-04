# Pruebas locales — HU-020

Pruebas automatizadas del servicio de embeddings (CLIP). Corren en local, **sin credenciales de AWS ni red**:
boto3, psycopg2 y la base se sustituyen, y una guardia bloquea cualquier conexión a hosts externos.
Las imágenes se generan en memoria; no hay fotos en el repositorio.

## Instalar

```bash
# Desde SERVICE_EMBEDDING/
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Linux/macOS: .venv/bin/python
```

## Correr

```bash
.venv/Scripts/python -m pytest -v          # pruebas rápidas (~6 s)
.venv/Scripts/python -m pytest -m modelo   # opcional: CLIP real, descarga ~600 MB de Hugging Face
```

Si `torch`/`transformers` no están instalados, `conftest.py` los simula y las pruebas del embedder se saltan.

## Qué cubre cada archivo

| Archivo | Qué prueba | Escenario HU-020 |
|---|---|---|
| `test_importa.py` | La app se importa sin AWS ni red; la guardia de red funciona | Base |
| `test_api.py` | `/health` (listo / no listo, carga al arrancar) y `/predict` (4 campos, mejor similitud, 4 decimales, empate, `Unknown`, imágenes no RGB, 400, 503, 422) | 1, 2, 3 |
| `test_model_store.py` | Carga única e idempotente; si falla la base no queda "listo" | 1 |
| `test_db.py` | Vectores en texto → matriz `float32` normalizada, metadatos, tablas configuradas; token IAM como contraseña y `sslmode=require` | 1, 6 |
| `test_embedder.py` | Vector 1D `float32` de norma 1, modelo cargado una vez, determinismo, imágenes RGBA/L/P; CLIP real (512) con `-m modelo` | 2 |
| `test_config_despliegue.py` | Mismo `CLIP_MODEL_ID` en `config.py`, `task_definition.json` y `Dockerfile`; puerto 8080; usuario no root; sin secretos; 2 vCPU / 4 GB | 5, 6 |
