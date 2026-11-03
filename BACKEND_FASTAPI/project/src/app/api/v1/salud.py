"""`GET /v1/health` y `GET /v1/health/ready` (ARCHITECTURE §4.2, §4.3, §5.3)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request

from app import __version__
from app.api.dependencias import obtener_ajustes
from app.clientes import embedding
from app.config import Settings
from app.db import sesion
from app.errores import ErrorApi
from app.esquemas.errores import ErrorRespuesta
from app.esquemas.salud import PreparacionRespuesta, SaludRespuesta
from app.logs import obtener_logger, registrar

log = obtener_logger(__name__)

router = APIRouter(prefix="/health", tags=["salud"])


@router.get("", response_model=SaludRespuesta, summary="Indicador de conexión")
async def salud(ajustes: Settings = Depends(obtener_ajustes)) -> SaludRespuesta:
    """No consulta la base ni embeddings: lo usan la app y el *health check* del contenedor."""
    return SaludRespuesta(estado="ok", version=__version__, commit=ajustes.commit_corto)


async def _motivo_base_caida(request: Request, ajustes: Settings) -> str | None:
    """`None` si la base responde `SELECT 1` en `DB_CONNECT_TIMEOUT_S`; si no, el motivo (sin secretos)."""
    motor = getattr(request.app.state, "motor", None)
    if motor is None:
        return getattr(request.app.state, "motivo_sin_motor", "configuracion_incompleta")
    try:
        await sesion.comprobar_conexion(motor, ajustes.db_connect_timeout_s)
    except sesion.BaseNoDisponible as exc:
        return str(exc)
    return None


@router.get(
    "/ready",
    response_model=PreparacionRespuesta,
    summary="Diagnóstico de dependencias",
    responses={503: {"model": ErrorRespuesta, "description": "BASE_NO_DISPONIBLE"}},
)
async def preparado(request: Request, ajustes: Settings = Depends(obtener_ajustes)) -> PreparacionRespuesta:
    """Estado de las dependencias, consultadas en paralelo.

    La base es obligatoria: si no responde (o faltan `DB_*`), `503 BASE_NO_DISPONIBLE`. `embedding` apagado (se
    enciende a mano, infra §3.4) **no** produce 503: se informa `no_disponible`.
    """
    motivo, listo = await asyncio.gather(_motivo_base_caida(request, ajustes), embedding.esta_listo(ajustes))
    if motivo is not None:
        registrar(log, "base_no_disponible", logging.WARNING, motivo=motivo)
        raise ErrorApi(503, "BASE_NO_DISPONIBLE")
    return PreparacionRespuesta(estado="ok", db="ok", embedding="ok" if listo else "no_disponible")
