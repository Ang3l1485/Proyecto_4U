"""Endpoints reservados (ARCHITECTURE §5.3 «Endpoints reservados», §4.13): responden `501 NO_IMPLEMENTADO`.

`router_publico` va en `/v1` sin autenticación; `router_admin`, dentro del router protegido de `/v1/admin`, así que
exige primero el token de admin (`401`/`403`) y después responde `501`. Cada lote diferido sustituye su ruta aquí por
la real y define antes su contrato en §5 (BE-5.1 ya lo hizo: `POST /v1/localize/frame` está en `localizar.py`).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.errores import ErrorApi
from app.esquemas.errores import ErrorRespuesta

_NO_IMPLEMENTADO = {501: {"model": ErrorRespuesta, "description": "NO_IMPLEMENTADO"}}

router_publico = APIRouter(tags=["reservados"])
router_admin = APIRouter(tags=["reservados"])


def _no_implementado() -> ErrorApi:
    return ErrorApi(501, "NO_IMPLEMENTADO")


@router_publico.get("/route", summary="Ruta a un destino (BE-5.3)", responses=_NO_IMPLEMENTADO)
async def ruta() -> None:
    raise _no_implementado()


@router_publico.post("/eventos", summary="Eventos de uso (BE-5.2)", responses=_NO_IMPLEMENTADO)
async def eventos() -> None:
    raise _no_implementado()


@router_admin.get("/stats/uso", summary="Estadísticas de uso (BE-5.2)", responses=_NO_IMPLEMENTADO)
async def estadisticas_uso() -> None:
    raise _no_implementado()
