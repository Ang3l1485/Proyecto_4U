# Imagen única del backend (ARCHITECTURE §5.9): procesos `api` (CMD por defecto), `worker` y `migrate`.
# Contexto de construcción: BACKEND_FASTAPI/project/ (infra §5.9). Plataforma: linux/amd64.
#
#   docker build --platform linux/amd64 --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t campus-locator/backend:local .
#
# Contiene src/app/ (como paquete `app`) y migrations/ (BE-1.2, que lee `python -m app.cli migrar`); src/ops/ y tests/
# quedan fuera (.dockerignore).

ARG PYTHON_IMAGEN=python:3.12-slim-bookworm

# --- Dependencias -------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGEN} AS dependencias

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Imagen final -------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGEN}

ARG GIT_COMMIT=desconocido

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/srv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_COMMIT=${GIT_COMMIT}

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app

COPY --from=dependencias /opt/venv /opt/venv
WORKDIR /srv
COPY src/app ./app
COPY migrations ./migrations

USER app
EXPOSE 8000

# Proceso `api`. `worker` y `migrate` (python -m app.cli migrar) sobrescriben el comando en su definición de tarea (§5.9).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
