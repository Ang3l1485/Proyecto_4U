"""Lugares (ARCHITECTURE §4.9, §5.3, §5.5), BE-3.1.

- `router_publico` (`/v1/places`, sin autenticación: ignora `Authorization`): `GET` con `lat`+`lng` opcionales (los dos
  o ninguno) y `categoria`.
- `router_admin` (`/v1/admin/places`, va en `RUTAS_ADMIN`, exige `requiere_admin`): `GET` con `q` y `categoria`,
  `POST`, `PUT /{id}` y `DELETE /{id}` (`204` también si no existe).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencias import obtener_motor
from app.dominio.enumerados import CategoriaLugar
from app.dominio.lugares import Q_MAX
from app.dominio.validaciones import motivo_texto_no_admitido
from app.errores import ErrorApi
from app.esquemas.errores import ErrorRespuesta
from app.esquemas.lugares import ListaLugares, LugarAdmin, LugarEntrada, LugarPublico
from app.seguridad.dependencias import UsuarioActual, requiere_admin
from app.servicios import lugares

router_publico = APIRouter(prefix="/places", tags=["lugares"])
router_admin = APIRouter(prefix="/places", tags=["lugares"])

_422 = {422: {"model": ErrorRespuesta, "description": "VALIDACION"}}
_404 = {404: {"model": ErrorRespuesta, "description": "NO_ENCONTRADO"}}
_409 = {409: {"model": ErrorRespuesta, "description": "NOMBRE_DUPLICADO"}}
_503 = {503: {"model": ErrorRespuesta, "description": "BASE_NO_DISPONIBLE"}}


def _validacion(campo: str, motivo: str) -> ErrorApi:
    return ErrorApi(422, "VALIDACION", detalle={"campos": [{"campo": campo, "motivo": motivo}]})


@router_publico.get(
    "",
    response_model=ListaLugares[LugarPublico],
    summary="Lugares (por distancia si se envía la posición; si no, por nombre)",
    responses=_422 | _503,
)
async def listar_lugares(
    request: Request,
    lat: float | None = Query(None, ge=-90, le=90, allow_inf_nan=False, description="Va junto con lng"),
    lng: float | None = Query(None, ge=-180, le=180, allow_inf_nan=False, description="Va junto con lat"),
    categoria: CategoriaLugar | None = Query(None),
) -> ListaLugares[LugarPublico]:
    if (lat is None) != (lng is None):
        falta = "lng" if lng is None else "lat"
        raise _validacion(falta, "lat y lng van juntos: falta este.")
    items = await lugares.listar_publico(obtener_motor(request), lat=lat, lng=lng, categoria=categoria)
    return ListaLugares[LugarPublico](items=items, total=len(items))


@router_admin.get("", response_model=ListaLugares[LugarAdmin], summary="Lugares para el panel", responses=_422)
async def listar_lugares_admin(
    request: Request,
    q: str | None = Query(None, max_length=Q_MAX, description="Contenido en el nombre, sin tildes ni mayúsculas"),
    categoria: CategoriaLugar | None = Query(None),
) -> ListaLugares[LugarAdmin]:
    if q is not None and (motivo := motivo_texto_no_admitido(q)) is not None:
        raise _validacion("q", motivo)
    items = await lugares.listar_admin(obtener_motor(request), q=q, categoria=categoria)
    return ListaLugares[LugarAdmin](items=items, total=len(items))


@router_admin.post("", status_code=201, response_model=LugarAdmin, summary="Crear un lugar", responses=_409 | _422)
async def crear_lugar(
    datos: LugarEntrada, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> LugarAdmin:
    try:
        return await lugares.crear(obtener_motor(request), usuario_id=usuario.id, datos=datos)
    except lugares.NombreDuplicado:
        raise ErrorApi(409, "NOMBRE_DUPLICADO") from None


@router_admin.put(
    "/{lugar_id}",
    response_model=LugarAdmin,
    summary="Reemplazar un lugar (todos los campos de LugarEntrada)",
    responses=_404 | _409 | _422,
)
async def reemplazar_lugar(
    lugar_id: uuid.UUID, datos: LugarEntrada, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> LugarAdmin:
    try:
        return await lugares.reemplazar(obtener_motor(request), usuario_id=usuario.id, lugar_id=lugar_id, datos=datos)
    except lugares.LugarNoEncontrado:
        raise ErrorApi(404, "NO_ENCONTRADO") from None
    except lugares.NombreDuplicado:
        raise ErrorApi(409, "NOMBRE_DUPLICADO") from None


@router_admin.delete(
    "/{lugar_id}",
    status_code=204,
    response_class=Response,
    summary="Borrar un lugar (sus imágenes quedan sin lugar; 204 también si no existe)",
    responses=_422,
)
async def borrar_lugar(
    lugar_id: uuid.UUID, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> Response:
    await lugares.borrar(obtener_motor(request), usuario_id=usuario.id, lugar_id=lugar_id)
    return Response(status_code=204)
