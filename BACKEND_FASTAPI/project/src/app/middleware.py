"""Middleware de solicitud: `X-Request-Id`, log de cada petición y red de seguridad para errores no previstos.

- Reutiliza el `X-Request-Id` del cliente si es razonable (≤ 128 caracteres `[A-Za-z0-9._:-]`); si no, genera un
  UUID v4. Lo devuelve en **todas** las respuestas (ARCHITECTURE §5.1) y lo deja en `request_id_actual` para que
  aparezca en cada línea de log (§5.10).
- Registra el evento `peticion` (método, ruta sin query string, estado, duración). La ruta no incluye la query string
  para no llevar nunca a los logs parámetros sensibles (§4.1).
- Si una excepción no controlada llega hasta aquí, responde `500 ERROR_INTERNO` con el formato de §5.1 y registra la
  traza en una sola línea JSON (evento `error_no_controlado`).

Es ASGI puro (no `BaseHTTPMiddleware`) para no interferir con respuestas en streaming ni con el contexto.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errores import respuesta_error
from app.logs import obtener_logger, registrar, request_id_actual

ENCABEZADO = "X-Request-Id"
_ENCABEZADO_BYTES = ENCABEZADO.lower().encode("latin-1")
_ID_VALIDO = re.compile(r"[A-Za-z0-9._:\-]{1,128}")

#: Rutas cuyo éxito se registra en DEBUG: el *health check* del contenedor las llama cada 30 s.
RUTAS_SILENCIOSAS = frozenset({"/v1/health"})

log = obtener_logger("app.solicitudes")


def _request_id_entrante(scope: Scope) -> str | None:
    for nombre, valor in scope.get("headers", ()):
        if nombre == _ENCABEZADO_BYTES:
            candidato = valor.decode("latin-1").strip()
            return candidato if _ID_VALIDO.fullmatch(candidato) else None
    return None


class MiddlewareSolicitud:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_entrante(scope) or str(uuid.uuid4())
        token = request_id_actual.set(request_id)
        inicio = time.perf_counter()
        respuesta = {"estado": 500, "iniciada": False}

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                respuesta["estado"] = mensaje["status"]
                respuesta["iniciada"] = True
                MutableHeaders(scope=mensaje)[ENCABEZADO] = request_id
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        except Exception:
            registrar(
                log,
                "error_no_controlado",
                logging.ERROR,
                metodo=scope.get("method"),
                ruta=scope.get("path"),
                exc_info=True,
            )
            if respuesta["iniciada"]:
                raise
            await respuesta_error(500, "ERROR_INTERNO")(scope, receive, enviar)
        finally:
            estado = int(respuesta["estado"])
            ruta = scope.get("path", "")
            nivel = logging.DEBUG if ruta in RUTAS_SILENCIOSAS and estado < 400 else logging.INFO
            registrar(
                log,
                "peticion",
                nivel,
                metodo=scope.get("method"),
                ruta=ruta,
                estado=estado,
                duracion_ms=round((time.perf_counter() - inicio) * 1000, 1),
            )
            request_id_actual.reset(token)
