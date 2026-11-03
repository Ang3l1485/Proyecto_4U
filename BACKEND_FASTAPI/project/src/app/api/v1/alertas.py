"""Alertas (ARCHITECTURE §4.11, §5.3, §5.5, ADR-BE-10), BE-3.3.

- `router_publico` (`/v1/alerts`, sin autenticación: ignora `Authorization`): `GET` con `desde` opcional (foto completa
  o diferencias).
- `router_admin` (`/v1/admin/alerts`, va en `RUTAS_ADMIN`, exige `requiere_admin`): `GET` con `q`, `tipo`, `prioridad`
  y `activa`; `POST /sincronizar`; `PUT /{id}` (crea, reemplaza o restaura; `If-Match` opcional) y `DELETE /{id}`
  (`204` también si no existe).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.api.dependencias import obtener_ajustes, obtener_motor
from app.dominio.alertas import Q_MAX, leer_if_match
from app.dominio.enumerados import PrioridadAlerta, TipoAlerta
from app.dominio.validaciones import motivo_texto_no_admitido
from app.errores import ErrorApi
from app.esquemas.alertas import (
    AlertaAdmin,
    AlertaEntrada,
    AlertasRespuesta,
    ListaAlertas,
    SincronizarPeticion,
    SincronizarRespuesta,
)
from app.esquemas.comun import FechaConZona
from app.esquemas.errores import ErrorRespuesta
from app.seguridad.dependencias import UsuarioActual, requiere_admin
from app.servicios import alertas

router_publico = APIRouter(prefix="/alerts", tags=["alertas"])
router_admin = APIRouter(prefix="/alerts", tags=["alertas"])

_422 = {422: {"model": ErrorRespuesta, "description": "VALIDACION"}}
_409 = {409: {"model": ErrorRespuesta, "description": "CONFLICTO_VERSION"}}
_503 = {503: {"model": ErrorRespuesta, "description": "BASE_NO_DISPONIBLE"}}
_201 = {201: {"model": AlertaAdmin, "description": "Creada, o restaurada si estaba borrada"}}


def _validacion(campo: str, motivo: str) -> ErrorApi:
    return ErrorApi(422, "VALIDACION", detalle={"campos": [{"campo": campo, "motivo": motivo}]})


@router_publico.get(
    "",
    response_model=AlertasRespuesta,
    summary="Alertas para la caché de la app: foto completa o diferencias desde `desde`",
    responses=_422 | _503,
)
async def alertas_publicas(
    request: Request,
    desde: FechaConZona | None = Query(
        None, description="`generado_en` de una respuesta anterior (ISO-8601 con zona; con `Z` no hace falta codificar)"
    ),
) -> AlertasRespuesta:
    ajustes = obtener_ajustes(request)
    return await alertas.foto(obtener_motor(request), desde=desde, dias_tombstone=ajustes.alertas_tombstone_dias)


@router_admin.get("", response_model=ListaAlertas, summary="Alertas para el panel (sin las borradas)", responses=_422)
async def listar_alertas_admin(
    request: Request,
    q: str | None = Query(None, max_length=Q_MAX, description="Contenido en el mensaje, sin tildes ni mayúsculas"),
    tipo: TipoAlerta | None = Query(None),
    prioridad: PrioridadAlerta | None = Query(None),
    activa: bool | None = Query(None),
) -> ListaAlertas:
    if q is not None and (motivo := motivo_texto_no_admitido(q)) is not None:
        raise _validacion("q", motivo)
    items = await alertas.listar_admin(obtener_motor(request), q=q, tipo=tipo, prioridad=prioridad, activa=activa)
    return ListaAlertas(items=items, total=len(items))


@router_admin.post(
    "/sincronizar",
    response_model=SincronizarRespuesta,
    summary="Aplicar una lista de cambios independientes (upsert o eliminar) y devolver el resultado de cada uno",
    responses=_422,
)
async def sincronizar_alertas(
    peticion: SincronizarPeticion, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> SincronizarRespuesta:
    return await alertas.sincronizar(obtener_motor(request), usuario_id=usuario.id, cambios=peticion.cambios)


@router_admin.put(
    "/{alerta_id}",
    response_model=AlertaAdmin,
    summary="Crear o reemplazar una alerta con el id que genera la app (If-Match opcional)",
    responses=_201 | _409 | _422,
)
async def guardar_alerta(
    alerta_id: uuid.UUID,
    datos: AlertaEntrada,
    request: Request,
    response: Response,
    usuario: UsuarioActual = Depends(requiere_admin),
    if_match: str | None = Header(None, description='Versión que se espera reemplazar (`3` o `"3"`)'),
) -> AlertaAdmin:
    version = None
    if if_match is not None:
        try:
            version = leer_if_match(if_match)
        except ValueError as exc:
            raise _validacion("If-Match", str(exc)) from None
    try:
        guardado = await alertas.guardar(
            obtener_motor(request),
            usuario_id=usuario.id,
            alerta_id=alerta_id,
            datos=datos,
            version_esperada=version,
        )
    except alertas.ConflictoVersion:
        raise ErrorApi(409, "CONFLICTO_VERSION") from None
    if guardado.creada:
        response.status_code = 201
    return guardado.alerta


@router_admin.delete(
    "/{alerta_id}",
    status_code=204,
    response_class=Response,
    summary="Borrar una alerta (tombstone; 204 también si no existe)",
    responses=_422,
)
async def borrar_alerta(
    alerta_id: uuid.UUID, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> Response:
    await alertas.borrar(obtener_motor(request), usuario_id=usuario.id, alerta_id=alerta_id)
    return Response(status_code=204)
