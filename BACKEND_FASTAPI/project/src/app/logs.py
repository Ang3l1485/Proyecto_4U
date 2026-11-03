"""Logs en JSON, una línea por evento (ARCHITECTURE §5.10).

Campos fijos: `ts`, `nivel`, `proceso`, `request_id`, `evento`; después, los campos propios del evento.
Nunca se registran tokens, contraseñas, URLs prefirmadas ni bytes de imagen (§4.1). En las trazas (`excepcion`) se
omite el `DETAIL` de los errores de PostgreSQL, que puede copiar la fila rechazada (p. ej. un hash de contraseña).

Uso:
    from app.logs import obtener_logger, registrar
    log = obtener_logger(__name__)
    registrar(log, "video_creado", video_id=str(video.id))
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Identificador de la petición en curso (lo fija el middleware de `X-Request-Id`).
request_id_actual: ContextVar[str | None] = ContextVar("request_id_actual", default=None)

_CAMPOS_FIJOS = ("ts", "nivel", "proceso", "request_id", "evento")
_EVENTO_GENERICO = "log"
_LOGGERS_RUIDOSOS = ("httpx", "httpcore", "botocore", "boto3", "urllib3", "s3transfer", "asyncio")
_OMITIDO = "(omitido)"
_LINEA_DETAIL = re.compile(r"^(\s*DETAIL:).*$", re.MULTILINE)


def _detalles_postgres(exc: BaseException | None) -> set[str]:
    """Los `detail` de los errores de PostgreSQL (asyncpg) de la cadena de excepciones."""
    detalles: set[str] = set()
    pendientes: list[Any] = [exc]
    vistas: set[int] = set()
    while pendientes:
        actual = pendientes.pop()
        if not isinstance(actual, BaseException) or id(actual) in vistas:
            continue
        vistas.add(id(actual))
        detalle = getattr(actual, "detail", None)
        if isinstance(detalle, str) and detalle.strip():
            detalles.add(detalle)
        pendientes += [getattr(actual, "orig", None), actual.__cause__, actual.__context__]
    return detalles


def traza_sin_datos(texto: str, exc: BaseException | None) -> str:
    """La traza sin el `DETAIL` de PostgreSQL: «Failing row contains (…)» o «Key (correo)=(…)» llevan valores."""
    for detalle in sorted(_detalles_postgres(exc), key=len, reverse=True):
        texto = texto.replace(detalle, _OMITIDO)
    return _LINEA_DETAIL.sub(rf"\1 {_OMITIDO}", texto)


class FiltroContexto(logging.Filter):
    """Copia en cada registro el `request_id` de la petición en curso (al emitirse, no al formatearse)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = request_id_actual.get()
        return True


class FormatoJson(logging.Formatter):
    """Convierte un `LogRecord` en una línea JSON con los campos de §5.10."""

    def __init__(self, proceso: str) -> None:
        super().__init__()
        self.proceso = proceso

    def format(self, record: logging.LogRecord) -> str:
        mensaje = record.getMessage()
        evento = getattr(record, "evento", None)
        datos: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "nivel": record.levelname,
            "proceso": self.proceso,
            "request_id": getattr(record, "request_id", None),
            "evento": evento or _EVENTO_GENERICO,
        }
        campos = getattr(record, "campos", None)
        if isinstance(campos, dict):
            for clave, valor in campos.items():
                if clave not in _CAMPOS_FIJOS:
                    datos[clave] = valor
        if not evento or mensaje != evento:
            datos["mensaje"] = mensaje
        datos["logger"] = record.name
        if record.exc_info:
            datos["excepcion"] = traza_sin_datos(self.formatException(record.exc_info), record.exc_info[1])
        return json.dumps(datos, ensure_ascii=False, default=str)


def crear_manejador(proceso: str, flujo: Any = None) -> logging.Handler:
    """Manejador que escribe JSON por línea en `flujo` (por defecto, la salida estándar: la recoge CloudWatch)."""
    manejador = logging.StreamHandler(flujo or sys.stdout)
    manejador.setFormatter(FormatoJson(proceso))
    manejador.addFilter(FiltroContexto())
    return manejador


def configurar_logs(proceso: str, nivel: str = "INFO") -> None:
    """Deja el logging del proceso en JSON por línea, incluidos los mensajes de uvicorn.

    Se llama al crear la app (uvicorn ya configuró sus loggers en texto; aquí se reemplazan) y al arrancar el
    `worker` o la CLI. El log de acceso de uvicorn se desactiva: cada petición la registra el middleware con su
    `request_id` (evento `peticion`).
    """
    raiz = logging.getLogger()
    for manejador in list(raiz.handlers):
        if getattr(manejador, "_campus_locator", False):
            raiz.removeHandler(manejador)
    nuevo = crear_manejador(proceso)
    nuevo._campus_locator = True  # type: ignore[attr-defined]
    raiz.addHandler(nuevo)
    raiz.setLevel(nivel)

    for nombre in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(nombre)
        logger.handlers.clear()
        logger.propagate = True
    acceso = logging.getLogger("uvicorn.access")
    acceso.handlers.clear()
    acceso.propagate = False
    acceso.disabled = True

    # Clientes HTTP y de AWS: en INFO/DEBUG registran URLs completas (podrían ser prefirmadas) y cabeceras.
    for nombre in _LOGGERS_RUIDOSOS:
        logging.getLogger(nombre).setLevel(logging.WARNING)


def obtener_logger(nombre: str) -> logging.Logger:
    return logging.getLogger(nombre)


def registrar(logger: logging.Logger, evento: str, nivel: int = logging.INFO, **campos: Any) -> None:
    """Registra `evento` con sus campos propios. `exc_info=True` adjunta la traza de la excepción en curso."""
    exc_info = campos.pop("exc_info", None)
    logger.log(nivel, evento, extra={"evento": evento, "campos": campos}, exc_info=exc_info)
