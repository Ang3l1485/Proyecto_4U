# Imagen de prueba «bootstrap» (ARCHITECTURE §5.11): responde 200 en GET /v1/health (:8000) y GET /health/ready
# (:8080) para que los servicios arranquen y se validen antes de que exista el código real. Se publica con la
# etiqueta bootstrap en campus-locator/backend y campus-locator/embedding (README.md).
FROM public.ecr.aws/docker/library/python:3.12-alpine

COPY servidor.py /srv/servidor.py
USER 10001:10001
EXPOSE 8000 8080

# El ENTRYPOINT recibe como argumentos el comando de la definición de tarea: servidor.py decide qué hacer con él.
ENTRYPOINT ["python", "-u", "/srv/servidor.py"]
