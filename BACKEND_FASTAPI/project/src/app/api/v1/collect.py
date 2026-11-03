"""Recolección (ARCHITECTURE §4.5, §5.4): `/v1/collect/videos…`. Va en `RUTAS_COLLECT` (exige `requiere_admin`)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencias import almacen_o_none, obtener_ajustes, obtener_motor, sin_almacen
from app.clientes.s3 import FalloS3
from app.config import Settings
from app.errores import ErrorApi
from app.esquemas.errores import ErrorRespuesta
from app.esquemas.videos import (
    ImagenesRegistradas,
    ImagenesRegistrar,
    SubidaCompletada,
    VideoCrear,
    VideoResumen,
)
from app.logs import obtener_logger, registrar
from app.seguridad.dependencias import UsuarioActual, requiere_admin
from app.servicios import recoleccion

log = obtener_logger(__name__)
router = APIRouter(prefix="/videos", tags=["recolección"])

_404 = {404: {"model": ErrorRespuesta, "description": "NO_ENCONTRADO"}}
_409 = {409: {"model": ErrorRespuesta, "description": "VIDEO_ELIMINADO"}}
_422 = {422: {"model": ErrorRespuesta, "description": "VALIDACION"}}
_500 = {500: {"model": ErrorRespuesta, "description": "ERROR_INTERNO (p. ej. falta S3_BUCKET_DATASET)"}}


def _error_video(exc: Exception) -> ErrorApi:
    if isinstance(exc, recoleccion.VideoEliminado):
        return ErrorApi(409, "VIDEO_ELIMINADO")
    return ErrorApi(404, "NO_ENCONTRADO")


@router.post(
    "",
    status_code=201,
    response_model=VideoResumen,
    summary="Crear el video de un recorrido (idempotente por ref_cliente)",
    responses={200: {"model": VideoResumen, "description": "Ya existía un video de este admin con ese ref_cliente"}}
    | _409
    | _422,
)
async def crear_video(
    datos: VideoCrear,
    request: Request,
    response: Response,
    usuario: UsuarioActual = Depends(requiere_admin),
) -> VideoResumen:
    motor = obtener_motor(request)
    try:
        resumen, creado = await recoleccion.crear_video(motor, usuario_id=usuario.id, datos=datos)
    except recoleccion.VideoEliminado as exc:
        raise _error_video(exc) from None
    if not creado:
        response.status_code = 200
    return resumen


@router.post(
    "/{video_id}/images",
    response_model=ImagenesRegistradas,
    summary="Registrar fotos y obtener URLs prefirmadas PUT",
    responses=_404 | _409 | _422 | _500,
)
async def registrar_imagenes(
    video_id: uuid.UUID,
    datos: ImagenesRegistrar,
    request: Request,
    ajustes: Settings = Depends(obtener_ajustes),
) -> ImagenesRegistradas:
    motor = obtener_motor(request)
    try:
        return await recoleccion.registrar_imagenes(
            motor, almacen_o_none(request), ajustes, video_id=video_id, imagenes=datos.imagenes
        )
    except recoleccion.AlmacenNoConfigurado:
        raise sin_almacen(request) from None
    except recoleccion.DatosNoValidos as exc:
        raise ErrorApi(422, "VALIDACION", detalle={"campos": exc.campos}) from None
    except (recoleccion.VideoNoEncontrado, recoleccion.VideoEliminado) as exc:
        raise _error_video(exc) from None
    except FalloS3 as exc:
        registrar(log, "s3_fallido", logging.ERROR, operacion="firmar", video_id=str(video_id), motivo=str(exc))
        raise ErrorApi(500, "ERROR_INTERNO") from None


@router.post(
    "/{video_id}/complete",
    response_model=SubidaCompletada,
    summary="Marcar la subida como terminada (HEAD en S3 de las pendientes) y devolver el conteo",
    responses=_404 | _409 | _500,
)
async def completar_subida(video_id: uuid.UUID, request: Request) -> SubidaCompletada:
    motor = obtener_motor(request)
    try:
        return await recoleccion.completar_subida(motor, almacen_o_none(request), video_id=video_id)
    except recoleccion.AlmacenNoConfigurado:
        raise sin_almacen(request) from None
    except (recoleccion.VideoNoEncontrado, recoleccion.VideoEliminado) as exc:
        raise _error_video(exc) from None
