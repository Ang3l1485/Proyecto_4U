# Verificación realizada

- Entorno virtual local creado con Python 3.11.
- Instalación completa de `requirements.txt` terminada correctamente.
- `pip check`: sin dependencias rotas.
- Imports reales de PyTorch 2.7.1+cpu, `AutoImageProcessor` y `AutoModel`: correctos.
- `pytest -q`: **9 pruebas aprobadas**. Hay una advertencia de deprecación de Starlette/AnyIO que no afecta el resultado.
- `compileall` sobre `app` y `scripts`: correcto.
- Ayuda de ambos clientes CLI: correcta.
- `docker compose config --quiet`: correcto, con `.env` creado a partir del ejemplo.

Límites de esta verificación: el motor de Docker Desktop estaba apagado, por lo que no se ejecutaron contenedores ni se construyó la imagen Docker. No se descargaron los pesos DINOv2 ni se ejecutó su inferencia. Las pruebas del pipeline usan Qdrant real en memoria y un extractor determinista de prueba. No había JPG reales adjuntos para medir precisión del reconocimiento. `scripts/check_model.py` permite comprobar descarga e inferencia real; el README describe la prueba con fotografías del campus.
