"""Errores de la API con el formato de ARCHITECTURE §5.1 y los códigos de §5.6.

- `ErrorApi`: la lanzan routers y servicios para responder un error del contrato.
- `registrar_manejadores(app)`: convierte en ese formato las excepciones de FastAPI/Starlette (404 de ruta, 405,
  validación, cuerpo mal formado), las `ErrorApi` y `sesion.BaseNoDisponible` (`503 BASE_NO_DISPONIBLE` con el evento
  `base_no_disponible`, BE-1.3).
- Los fallos no previstos (500 `ERROR_INTERNO`) los atrapa el middleware de solicitud (`app.middleware`), que es el
  único que puede añadir `X-Request-Id` a esa respuesta.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import sesion
from app.logs import obtener_logger, registrar

log = obtener_logger(__name__)

#: Código de §5.6 que corresponde a un estado HTTP cuando la excepción no trae uno propio.
CODIGO_POR_ESTADO: dict[int, str] = {
    400: "SOLICITUD_INVALIDA",
    401: "NO_AUTENTICADO",
    403: "SIN_PERMISOS",
    404: "NO_ENCONTRADO",
    405: "SOLICITUD_INVALIDA",
    422: "VALIDACION",
    500: "ERROR_INTERNO",
    501: "NO_IMPLEMENTADO",
}

MENSAJE_POR_CODIGO: dict[str, str] = {
    "SOLICITUD_INVALIDA": "La solicitud está mal formada.",
    "FOTOS_INVALIDAS": "Las fotos enviadas no son válidas.",
    "NO_AUTENTICADO": "Hace falta iniciar sesión.",
    "TOKEN_INVALIDO": "La sesión no es válida. Inicia sesión de nuevo.",
    "TOKEN_EXPIRADO": "La sesión expiró. Inicia sesión de nuevo.",
    "CREDENCIALES_INVALIDAS": "Correo o contraseña incorrectos.",
    "SIN_PERMISOS": "No tienes permisos para esta operación.",
    "NO_ENCONTRADO": "El recurso no existe.",
    "VIDEO_ELIMINADO": "El video fue eliminado.",
    "NOMBRE_DUPLICADO": "Ya existe un lugar con ese nombre (sin distinguir mayúsculas ni tildes).",
    "CONFLICTO_VERSION": "La alerta no está en la versión de If-Match: cambió o no existe. Vuelve a leerla.",
    "IMAGEN_NO_SUBIDA": "La foto todavía no está subida: no hay nada que procesar.",
    "VALIDACION": "Hay campos con valores no válidos.",
    "ERROR_INTERNO": "Error interno del servidor. Indica el X-Request-Id al reportarlo.",
    "NO_IMPLEMENTADO": "Esta operación aún no está disponible.",
    "BASE_NO_DISPONIBLE": "La base de datos no está disponible.",
    "SERVICIO_OCUPADO": "El servicio está ocupado. Inténtalo de nuevo en unos segundos.",
    "EMBEDDING_NO_DISPONIBLE": "El servicio de embeddings no está disponible.",
}

_UBICACIONES = {"body", "query", "path", "header", "cookie"}


class ErrorApi(Exception):
    """Error del contrato: se responde como `{"error": {codigo, mensaje, detalle}}` con `estado_http`."""

    def __init__(
        self,
        estado_http: int,
        codigo: str,
        mensaje: str | None = None,
        detalle: Mapping[str, Any] | None = None,
        encabezados: Mapping[str, str] | None = None,
    ) -> None:
        self.estado_http = estado_http
        self.codigo = codigo
        self.mensaje = mensaje or MENSAJE_POR_CODIGO.get(codigo, "Error.")
        self.detalle = dict(detalle) if detalle is not None else None
        self.encabezados = dict(encabezados) if encabezados else None
        super().__init__(f"{estado_http} {codigo}")


def cuerpo_error(codigo: str, mensaje: str, detalle: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"codigo": codigo, "mensaje": mensaje, "detalle": dict(detalle) if detalle is not None else None}}


def respuesta_error(
    estado_http: int,
    codigo: str,
    mensaje: str | None = None,
    detalle: Mapping[str, Any] | None = None,
    encabezados: Mapping[str, str] | None = None,
) -> JSONResponse:
    texto = mensaje or MENSAJE_POR_CODIGO.get(codigo, "Error.")
    return JSONResponse(
        status_code=estado_http,
        content=cuerpo_error(codigo, texto, detalle),
        headers=dict(encabezados) if encabezados else None,
    )


def _codigo_para_estado(estado_http: int) -> str:
    if estado_http in CODIGO_POR_ESTADO:
        return CODIGO_POR_ESTADO[estado_http]
    return "ERROR_INTERNO" if estado_http >= 500 else "SOLICITUD_INVALIDA"


def nombre_campo(ubicacion: Sequence[str | int]) -> str:
    """`("body", "inicio", "lat")` → `inicio.lat`; `("query", "k")` → `k`."""
    partes = list(ubicacion)
    if len(partes) > 1 and partes[0] in _UBICACIONES:
        partes = partes[1:]
    return ".".join(str(p) for p in partes) or "cuerpo"


def motivo_en_espanol(error: Mapping[str, Any]) -> str:
    """Traduce los errores más comunes de Pydantic; el resto conserva su mensaje original."""
    tipo = error.get("type", "")
    ctx = error.get("ctx") or {}
    mensaje = str(error.get("msg", "Valor no válido."))
    plantillas = {
        "missing": "Campo obligatorio.",
        "extra_forbidden": "Campo no permitido.",
        "greater_than_equal": "Debe ser mayor o igual que {ge}.",
        "greater_than": "Debe ser mayor que {gt}.",
        "less_than_equal": "Debe ser menor o igual que {le}.",
        "less_than": "Debe ser menor que {lt}.",
        "string_too_short": "Debe tener al menos {min_length} caracteres.",
        "string_too_long": "Debe tener como máximo {max_length} caracteres.",
        "too_short": "Debe tener al menos {min_length} elementos.",
        "too_long": "Debe tener como máximo {max_length} elementos.",
        "string_type": "Debe ser un texto.",
        "int_type": "Debe ser un número entero.",
        "int_parsing": "Debe ser un número entero.",
        "int_from_float": "Debe ser un número entero.",
        "float_type": "Debe ser un número.",
        "float_parsing": "Debe ser un número.",
        "bool_type": "Debe ser verdadero o falso.",
        "bool_parsing": "Debe ser verdadero o falso.",
        "uuid_type": "Debe ser un UUID.",
        "uuid_parsing": "Debe ser un UUID.",
        "datetime_type": "Debe ser una fecha ISO-8601.",
        "datetime_parsing": "Debe ser una fecha ISO-8601.",
        "datetime_from_date_parsing": "Debe ser una fecha ISO-8601.",
        "enum": "Valor no permitido. Admitidos: {expected}.",
        "literal_error": "Valor no permitido. Admitidos: {expected}.",
        "list_type": "Debe ser una lista.",
        "dict_type": "Debe ser un objeto.",
        "model_type": "Debe ser un objeto.",
    }
    if tipo in plantillas:
        try:
            return plantillas[tipo].format(**ctx)
        except (KeyError, IndexError, ValueError):
            return mensaje
    if tipo == "value_error":
        return mensaje.removeprefix("Value error, ")
    return mensaje


def _detalle_validacion(errores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"campos": [{"campo": nombre_campo(e.get("loc", ())), "motivo": motivo_en_espanol(e)} for e in errores]}


async def _manejar_error_api(request: Request, exc: ErrorApi) -> JSONResponse:
    if exc.estado_http >= 500:
        registrar(log, "error_api", logging.ERROR, estado=exc.estado_http, codigo=exc.codigo)
    return respuesta_error(exc.estado_http, exc.codigo, exc.mensaje, exc.detalle, exc.encabezados)


async def _manejar_base_no_disponible(request: Request, exc: sesion.BaseNoDisponible) -> JSONResponse:
    registrar(log, "base_no_disponible", logging.WARNING, motivo=str(exc))
    return respuesta_error(503, "BASE_NO_DISPONIBLE")


async def _manejar_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codigo = _codigo_para_estado(exc.status_code)
    mensaje = MENSAJE_POR_CODIGO.get(codigo, "Error.")
    detalle: dict[str, Any] | None = None
    encabezados = dict(exc.headers) if exc.headers else None
    if exc.status_code == 405:
        mensaje = "Método no permitido en esta ruta."
        permitidos = (encabezados or {}).get("Allow") or (encabezados or {}).get("allow")
        if permitidos:
            detalle = {"metodos_permitidos": [m.strip() for m in permitidos.split(",") if m.strip()]}
    return respuesta_error(exc.status_code, codigo, mensaje, detalle, encabezados)


async def _manejar_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    errores = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errores):
        return respuesta_error(400, "SOLICITUD_INVALIDA", "El cuerpo no es un JSON válido.")
    return respuesta_error(422, "VALIDACION", detalle=_detalle_validacion(errores))


def registrar_manejadores(app: FastAPI) -> None:
    # Starlette tipa los manejadores con `Exception`; cada uno recibe solo su clase.
    app.add_exception_handler(ErrorApi, _manejar_error_api)
    app.add_exception_handler(sesion.BaseNoDisponible, _manejar_base_no_disponible)
    app.add_exception_handler(StarletteHTTPException, _manejar_http)
    app.add_exception_handler(RequestValidationError, _manejar_validacion)
