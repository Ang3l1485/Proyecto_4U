"""Resumen del panel (ARCHITECTURE §4.7, §5.5): `GET /v1/admin/stats` (BE-2.3). Va en `RUTAS_ADMIN` (exige
`requiere_admin`). No tiene parámetros: los de la URL se ignoran. `GET /v1/admin/stats/uso` sigue siendo el reservado
de BE-5.2 (`reservados.router_admin`)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.dependencias import obtener_motor
from app.esquemas.estadisticas import ResumenPanel
from app.servicios import estadisticas

router = APIRouter(prefix="/stats", tags=["panel"])


@router.get("", response_model=ResumenPanel, summary="Resumen del panel: totales y último video")
async def resumen_panel(request: Request) -> ResumenPanel:
    return await estadisticas.resumen(obtener_motor(request))
