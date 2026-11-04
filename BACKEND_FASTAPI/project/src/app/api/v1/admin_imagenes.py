"""Imágenes del panel (BE-4.1, ARCHITECTURE §4.12 y §5.5): `/v1/admin/images`. Va en `RUTAS_ADMIN` (exige
`requiere_admin`). Los routers solo validan, llaman a `servicios.imagenes` y traducen sus errores (§5.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencias import almacen_o_none, obtener_ajustes, obtener_colas, obtener_motor, sin_cola
from app.api.v1.admin_videos import PAGINA_TOPE, error_cola
from app.clientes.sqs import FalloSqs
from app.config import Settings
from app.dominio.enumerados import CalidadImagen, EstadoImagen
from app.dominio.validaciones import motivo_texto_no_admitido
from app.errores import ErrorApi
from app.esquemas.comun import Pagina
from app.esquemas.errores import ErrorRespuesta
from app.esquemas.videos import Q_MAX, ImagenAdmin, ImagenDetalle, ImagenEditar, ImagenesLote, LoteResultado
from app.seguridad.dependencias import UsuarioActual, requiere_admin
from app.servicios import imagenes, videos

router = APIRouter(prefix="/images", tags=["imagenes"])

NO_ENCONTRADA = {404: {"model": ErrorRespuesta, "description": "NO_ENCONTRADO (también si su video está eliminado)"}}
MOTIVO_LUGAR = "No existe un lugar con ese id."


def _validacion(campo: str, motivo: str) -> ErrorApi:
    return ErrorApi(422, "VALIDACION", detalle={"campos": [{"campo": campo, "motivo": motivo}]})


@router.get(
    "",
    response_model=Pagina[ImagenAdmin],
    summary="Listar imágenes (sin las de videos eliminados)",
    responses={422: {"model": ErrorRespuesta, "description": "VALIDACION"}},
)
async def listar_imagenes(
    request: Request,
    video_id: uuid.UUID | None = Query(None),
    lugar_id: uuid.UUID | None = Query(None),
    estado: EstadoImagen | None = Query(None),
    calidad: CalidadImagen | None = Query(None),
    q: str | None = Query(None, max_length=Q_MAX, description="Contenido del nombre del video o de las notas"),
    pagina: int = Query(1, ge=1, le=PAGINA_TOPE),
    por_pagina: int | None = Query(None, ge=1, description="Por defecto PAGINA_POR_DEFECTO; máximo PAGINA_MAX"),
    ajustes: Settings = Depends(obtener_ajustes),
) -> Pagina[ImagenAdmin]:
    if q is not None and (motivo := motivo_texto_no_admitido(q)) is not None:
        raise _validacion("q", motivo)
    if por_pagina is not None and por_pagina > ajustes.pagina_max:
        raise _validacion("por_pagina", f"Debe ser menor o igual que {ajustes.pagina_max}.")
    return await imagenes.listar(
        obtener_motor(request),
        almacen_o_none(request),
        ajustes.presign_get_ttl_s,
        video_id=video_id,
        lugar_id=lugar_id,
        estado=estado,
        calidad=calidad,
        q=(q or "").strip() or None,
        pagina=pagina,
        por_pagina=por_pagina or ajustes.pagina_por_defecto,
    )


@router.post(
    "/lote",
    response_model=LoteResultado,
    summary="Eliminar o reasignar varias imágenes, cada una por separado",
    responses={422: {"model": ErrorRespuesta, "description": "VALIDACION"}},
)
async def lote_imagenes(
    datos: ImagenesLote, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> LoteResultado:
    if datos.accion == "reasignar" and "lugar_id" not in datos.model_fields_set:
        raise _validacion("lugar_id", "Con accion = reasignar hace falta lugar_id (un id o null).")
    try:
        return await imagenes.lote(
            obtener_motor(request),
            obtener_colas(request).purga,
            usuario_id=usuario.id,
            accion=datos.accion,
            ids=datos.ids,
            lugar_id=datos.lugar_id,
        )
    except imagenes.LugarNoExiste:
        raise _validacion("lugar_id", MOTIVO_LUGAR) from None
    except videos.ColaNoConfigurada as exc:
        raise sin_cola(exc.variable) from None


@router.get("/{imagen_id}", response_model=ImagenDetalle, summary="Detalle de una imagen", responses=NO_ENCONTRADA)
async def detalle_imagen(
    imagen_id: uuid.UUID, request: Request, ajustes: Settings = Depends(obtener_ajustes)
) -> ImagenDetalle:
    try:
        return await imagenes.detalle(obtener_motor(request), almacen_o_none(request), ajustes, imagen_id)
    except imagenes.ImagenNoEncontrada:
        raise ErrorApi(404, "NO_ENCONTRADO") from None


@router.patch(
    "/{imagen_id}",
    response_model=ImagenAdmin,
    summary="Editar coordenada, lugar, calidad o notas",
    responses={**NO_ENCONTRADA, 422: {"model": ErrorRespuesta, "description": "VALIDACION"}},
)
async def editar_imagen(
    imagen_id: uuid.UUID,
    datos: ImagenEditar,
    request: Request,
    ajustes: Settings = Depends(obtener_ajustes),
    usuario: UsuarioActual = Depends(requiere_admin),
) -> ImagenAdmin:
    enviados = datos.model_fields_set
    if ("lat" in enviados) != ("lng" in enviados):
        falta = "lng" if "lat" in enviados else "lat"
        raise _validacion(falta, "lat y lng van juntos: falta este.")
    for campo in ("lat", "lng", "calidad"):
        if campo in enviados and getattr(datos, campo) is None:
            raise _validacion(campo, "No puede ser null.")
    cambios = {campo: getattr(datos, campo) for campo in imagenes.CAMPOS_EDITABLES if campo in enviados}
    try:
        return await imagenes.editar(
            obtener_motor(request),
            almacen_o_none(request),
            ajustes,
            usuario_id=usuario.id,
            imagen_id=imagen_id,
            cambios=cambios,
        )
    except imagenes.ImagenNoEncontrada:
        raise ErrorApi(404, "NO_ENCONTRADO") from None
    except imagenes.LugarNoExiste:
        raise _validacion("lugar_id", MOTIVO_LUGAR) from None


@router.delete(
    "/{imagen_id}",
    status_code=204,
    response_class=Response,
    summary="Borrar una imagen: retira su vector al instante y encola purgar_imagen",
    responses=NO_ENCONTRADA,
)
async def borrar_imagen(
    imagen_id: uuid.UUID, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> Response:
    try:
        await imagenes.eliminar(
            obtener_motor(request), obtener_colas(request).purga, usuario_id=usuario.id, imagen_id=imagen_id
        )
    except imagenes.ImagenNoEncontrada:
        raise ErrorApi(404, "NO_ENCONTRADO") from None
    except videos.ColaNoConfigurada as exc:
        raise sin_cola(exc.variable) from None
    except FalloSqs as exc:
        raise error_cola(exc, "purga") from None
    return Response(status_code=204)


@router.post(
    "/{imagen_id}/reprocesar",
    status_code=202,
    response_class=Response,
    summary="Volver a procesar una imagen (vuelve a subida y se encola reprocesar_imagen)",
    responses={**NO_ENCONTRADA, 409: {"model": ErrorRespuesta, "description": "IMAGEN_NO_SUBIDA"}},
)
async def reprocesar_imagen(
    imagen_id: uuid.UUID, request: Request, usuario: UsuarioActual = Depends(requiere_admin)
) -> Response:
    try:
        await imagenes.reprocesar(
            obtener_motor(request), obtener_colas(request).ingesta, usuario_id=usuario.id, imagen_id=imagen_id
        )
    except imagenes.ImagenNoEncontrada:
        raise ErrorApi(404, "NO_ENCONTRADO") from None
    except imagenes.ImagenNoSubida:
        raise ErrorApi(409, "IMAGEN_NO_SUBIDA") from None
    except videos.ColaNoConfigurada as exc:
        raise sin_cola(exc.variable) from None
    except FalloSqs as exc:
        raise error_cola(exc, "ingesta") from None
    return Response(status_code=202)
