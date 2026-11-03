"""Recolección del dataset (ARCHITECTURE §4.5, §5.4, ADR-BE-14): crear el video, registrar fotos con URLs prefirmadas
`PUT` y completar la subida.

- `crear_video(motor, usuario_id=, datos=)` → `(VideoResumen, creado)`: idempotente por (admin, `ref_cliente`).
- `registrar_imagenes(motor, almacen, ajustes, video_id=, imagenes=)` → `ImagenesRegistradas`: idempotente por
  (`video_id`, `orden`); a las fotos repetidas que siguen `pendiente_subida` les hace `HEAD` y, si el objeto ya está,
  las pasa a `subida` sin URL.
- `completar_subida(motor, almacen, video_id=)` → `SubidaCompletada`: `HEAD` de las `pendiente_subida`, paso a `subida`
  de las que están, `subida_completa_en` y estado.
- `bloquear_video(conexion, video_id)` → `EstadoVideo | None`: `SELECT … FOR UPDATE` de la fila del video.
- `recalcular_estado(conexion, video_id)` → `(EstadoVideo, Conteo)`: deriva y guarda el estado del video
  (`dominio.recoleccion.estado_video`); el `worker` (BE-2.2) lo llama tras cambiar el estado de una foto.

`almacen` puede ser `None` (falta `S3_BUCKET_DATASET`): se comprueba **después** de mirar el video, así un video
inexistente da `VideoNoEncontrado` aunque falte el bucket; si hace falta S3, `AlmacenNoConfigurado`.

Concurrencia, **orden de bloqueo: video → imágenes, siempre**. Toda transacción que cambie fotos de un video bloquea
primero la fila del video (`bloquear_video`) y después las de `imagenes`; así dos lotes del mismo video, un lote y un
`complete`, o el `worker` (BE-2.2), van en fila y no pueden bloquearse entre sí. Los `HEAD` y las firmas se hacen fuera
de las transacciones (la conexión no espera a S3).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clientes.s3 import AlmacenS3, FalloS3, ObjetoS3, consultar_varios, firmar_puts
from app.config import Settings
from app.db import sesion
from app.db.modelos import SECUENCIA_NUMERO_VIDEO, Imagen, Video
from app.dominio.enumerados import EstadoImagen, EstadoVideo
from app.dominio.recoleccion import ENCABEZADOS_PUT, Conteo, clave_dataset, estado_video
from app.esquemas.videos import (
    ENTERO_MAX,
    ConteoFotos,
    ImagenesRegistradas,
    ImagenRegistrada,
    ImagenRegistro,
    SubidaCompletada,
    SubidaPut,
    VideoCrear,
    VideoResumen,
)
from app.logs import obtener_logger, registrar
from app.servicios import videos
from app.servicios.videos import VideoEliminado, VideoNoEncontrado

log = obtener_logger(__name__)

#: `imagenes_orden_check` (§5.7): `REC_MAX_FOTOS_VIDEO` no puede subir el máximo de `orden` por encima de esto.
ORDEN_MAX_ESQUEMA = 200

__all__ = [
    "AlmacenNoConfigurado",
    "DatosNoValidos",
    "VideoEliminado",
    "VideoNoEncontrado",
    "bloquear_video",
    "completar_subida",
    "crear_video",
    "recalcular_estado",
    "registrar_imagenes",
    "validar_lote",
]


class AlmacenNoConfigurado(Exception):
    """Hace falta S3 y `api` no tiene cliente (falta `S3_BUCKET_DATASET`): el router responde `500 ERROR_INTERNO`."""


class DatosNoValidos(Exception):
    """Límites de §5.10 que no cumple la petición; `campos` = `detalle.campos` de `422 VALIDACION`."""

    def __init__(self, campos: list[dict[str, str]]) -> None:
        self.campos = campos
        super().__init__("; ".join(f"{c['campo']}: {c['motivo']}" for c in campos))


# --- Ayudas -------------------------------------------------------------------------------------------------------
async def bloquear_video(conexion: AsyncConnection, video_id: uuid.UUID) -> EstadoVideo | None:
    """`SELECT estado … FOR UPDATE` de la fila del video dentro de la transacción en curso: su estado, o `None` si no
    existe. Es el primer bloqueo de toda transacción que cambie fotos del video (orden video → imágenes). No lanza por
    un video `eliminado`: quien llama decide (la recolección responde 409; el `worker` descarta el mensaje)."""
    consulta = select(Video.estado).where(Video.id == video_id).with_for_update()
    return (await conexion.execute(consulta)).scalar_one_or_none()


async def _exigir_video_activo(conexion: AsyncConnection, video_id: uuid.UUID, *, bloquear: bool = False) -> None:
    if bloquear:
        estado = await bloquear_video(conexion, video_id)
    else:
        estado = (await conexion.execute(select(Video.estado).where(Video.id == video_id))).scalar_one_or_none()
    if estado is None:
        raise VideoNoEncontrado(str(video_id))
    if estado == EstadoVideo.eliminado:
        raise VideoEliminado(str(video_id))


def _exigir_almacen(almacen: AlmacenS3 | None) -> AlmacenS3:
    if almacen is None:
        raise AlmacenNoConfigurado("falta S3_BUCKET_DATASET")
    return almacen


async def recalcular_estado(conexion: AsyncConnection, video_id: uuid.UUID) -> tuple[EstadoVideo, Conteo]:
    """Cuenta las fotos por estado, deriva el estado del video (§5.5, ADR-BE-14) y lo guarda si cambió. Un video
    `eliminado` no cambia. Va dentro de la transacción que cambió las fotos, que ya bloqueó el video con
    `bloquear_video` (orden video → imágenes)."""
    fila = (await conexion.execute(select(Video.estado, Video.subida_completa_en).where(Video.id == video_id))).first()
    if fila is None:
        raise VideoNoEncontrado(str(video_id))
    conteo = await videos.contar(conexion, video_id)
    if fila.estado == EstadoVideo.eliminado:
        return EstadoVideo.eliminado, conteo
    nuevo = estado_video(conteo, fila.subida_completa_en is not None)
    if nuevo != fila.estado:
        await conexion.execute(update(Video).where(Video.id == video_id).values(estado=nuevo))
    return nuevo, conteo


def validar_lote(imagenes: Sequence[ImagenRegistro], ajustes: Settings) -> None:
    """Límites de §5.10: como mucho `REC_MAX_LOTE` fotos, `orden` ≤ `REC_MAX_FOTOS_VIDEO` (y ≤ 200, §5.7) y único en la
    petición, `bytes` ≤ `REC_MAX_BYTES_FOTO`. Lanza `DatosNoValidos`."""
    campos: list[dict[str, str]] = []
    if len(imagenes) > ajustes.rec_max_lote:
        campos.append({"campo": "imagenes", "motivo": f"Debe tener como máximo {ajustes.rec_max_lote} elementos."})
    orden_max = min(ajustes.rec_max_fotos_video, ORDEN_MAX_ESQUEMA)
    vistos: set[int] = set()
    for indice, imagen in enumerate(imagenes):
        if imagen.orden > orden_max:
            campos.append({"campo": f"imagenes.{indice}.orden", "motivo": f"Debe ser menor o igual que {orden_max}."})
        elif imagen.orden in vistos:
            campos.append({"campo": f"imagenes.{indice}.orden", "motivo": "Repetido en la misma petición."})
        vistos.add(imagen.orden)
        if imagen.bytes > ajustes.rec_max_bytes_foto:
            campos.append(
                {
                    "campo": f"imagenes.{indice}.bytes",
                    "motivo": f"Debe ser menor o igual que {ajustes.rec_max_bytes_foto}.",
                }
            )
    if campos:
        raise DatosNoValidos(campos)


def _valores_subida(objeto: ObjetoS3) -> dict[str, Any]:
    """`subida` con el tamaño y el ETag del HEAD (un objeto de más de 2 GiB no cabe en `integer`: `bytes` queda nulo y
    el `worker` lo rechazará por tamaño)."""
    return {
        "estado": EstadoImagen.subida,
        "bytes": objeto.bytes if objeto.bytes <= ENTERO_MAX else None,
        "etag": objeto.etag,
    }


def _resumir_fallos(resultados: dict[str, ObjetoS3 | FalloS3 | None], video_id: uuid.UUID) -> int:
    fallos = [r for r in resultados.values() if isinstance(r, FalloS3)]
    if fallos:
        registrar(
            log,
            "s3_fallido",
            logging.WARNING,
            operacion="head",
            video_id=str(video_id),
            claves=len(fallos),
            motivo=str(fallos[0]),
        )
    return len(fallos)


# --- Casos de uso -------------------------------------------------------------------------------------------------
async def crear_video(motor: AsyncEngine, *, usuario_id: uuid.UUID, datos: VideoCrear) -> tuple[VideoResumen, bool]:
    """Crea el video (`pendiente`, `numero` de la secuencia, `nombre` o `video_<numero>`) o, si el admin ya tiene uno
    con ese `ref_cliente`, devuelve ese sin cambiarlo (`creado = False`). `VideoEliminado` si el existente está
    eliminado."""
    por_ref = select(Video.id, Video.estado).where(
        Video.creado_por == usuario_id, Video.ref_cliente == datos.ref_cliente
    )
    async with sesion.transaccion(motor) as conexion:
        existente = (await conexion.execute(por_ref)).first()
        video_id: uuid.UUID | None = None
        if existente is None:
            numero = (await conexion.execute(select(SECUENCIA_NUMERO_VIDEO.next_value()))).scalar_one()
            inicio = datos.inicio
            video_id = (
                await conexion.execute(
                    insert(Video)
                    .values(
                        numero=numero,
                        nombre=datos.nombre or f"video_{numero}",
                        ref_cliente=datos.ref_cliente,
                        iniciado_en=datos.iniciado_en,
                        finalizado_en=datos.finalizado_en,
                        duracion_s=datos.duracion_s,
                        distancia_m=datos.distancia_m,
                        pasos=datos.pasos,
                        inicio_lat=inicio.lat if inicio else None,
                        inicio_lng=inicio.lng if inicio else None,
                        inicio_rumbo=inicio.rumbo if inicio else None,
                        total_fotos_declaradas=datos.total_fotos,
                        dispositivo=datos.dispositivo,
                        app_version=datos.app_version,
                        creado_por=usuario_id,
                    )
                    .on_conflict_do_nothing(index_elements=["creado_por", "ref_cliente"])
                    .returning(Video.id)
                )
            ).scalar_one_or_none()
            if video_id is None:  # otra petición con el mismo ref_cliente lo creó entre la búsqueda y el INSERT
                existente = (await conexion.execute(por_ref)).first()
        creado = video_id is not None
        if not creado:
            if existente.estado == EstadoVideo.eliminado:
                raise VideoEliminado(str(existente.id))
            video_id = existente.id
        resumen = await videos.resumen(conexion, video_id)
    registrar(log, "video_creado", video_id=str(video_id), numero=resumen.numero, nuevo=creado)
    return resumen, creado


@dataclass
class _Plan:
    orden: int
    imagen_id: uuid.UUID
    estado: EstadoImagen
    clave: str | None  # clave a firmar (solo si queda `pendiente_subida`)


async def registrar_imagenes(
    motor: AsyncEngine,
    almacen: AlmacenS3 | None,
    ajustes: Settings,
    *,
    video_id: uuid.UUID,
    imagenes: Sequence[ImagenRegistro],
) -> ImagenesRegistradas:
    """Registra o actualiza cada foto y devuelve, en el orden de la petición, su `id`, su estado y la URL `PUT` de las
    que quedan `pendiente_subida` (las demás, `subida = null`). Lanza `DatosNoValidos`, `VideoNoEncontrado`,
    `VideoEliminado`, `AlmacenNoConfigurado` (tras comprobar el video, antes de escribir nada) o `FalloS3` (al firmar;
    las fotos ya quedaron registradas y repetir es seguro)."""
    validar_lote(imagenes, ajustes)
    ordenes = [imagen.orden for imagen in imagenes]
    columnas = (Imagen.id, Imagen.orden, Imagen.estado, Imagen.s3_key)

    # 1. Qué fotos repetidas siguen pendientes (sin bloquear: el HEAD va fuera de la transacción).
    async with sesion.transaccion(motor) as conexion:
        await _exigir_video_activo(conexion, video_id)
        almacen = _exigir_almacen(almacen)
        previas = (
            await conexion.execute(select(*columnas).where(Imagen.video_id == video_id, Imagen.orden.in_(ordenes)))
        ).all()
    vistas = await consultar_varios(
        almacen, [fila.s3_key for fila in previas if fila.estado == EstadoImagen.pendiente_subida]
    )
    _resumir_fallos(vistas, video_id)

    # 2. Escribir con el video bloqueado (lo de 1 pudo cambiar entretanto).
    planes: list[_Plan] = []
    cuentas = {"nuevas": 0, "actualizadas": 0, "marcadas_subida": 0, "sin_cambios": 0}
    async with sesion.transaccion(motor) as conexion:
        await _exigir_video_activo(conexion, video_id, bloquear=True)
        actuales = {
            fila.orden: fila
            for fila in await conexion.execute(
                select(*columnas).where(Imagen.video_id == video_id, Imagen.orden.in_(ordenes)).with_for_update()
            )
        }
        nuevas: list[dict[str, Any]] = []
        for imagen in imagenes:
            metadatos = {
                "lat": imagen.lat,
                "lng": imagen.lng,
                "rumbo": imagen.rumbo,
                "capturada_en": imagen.capturada_en,
                "bytes_declarados": imagen.bytes,
            }
            fila = actuales.get(imagen.orden)
            if fila is None:
                imagen_id = uuid.uuid4()
                clave = clave_dataset(video_id, imagen_id)
                nuevas.append(
                    {"id": imagen_id, "video_id": video_id, "orden": imagen.orden, "s3_key": clave, **metadatos}
                )
                planes.append(_Plan(imagen.orden, imagen_id, EstadoImagen.pendiente_subida, clave))
                cuentas["nuevas"] += 1
            elif fila.estado == EstadoImagen.pendiente_subida:
                objeto = vistas.get(fila.s3_key)
                if isinstance(objeto, ObjetoS3):
                    valores, estado, clave = _valores_subida(objeto), EstadoImagen.subida, None
                    cuentas["marcadas_subida"] += 1
                else:
                    valores, estado, clave = metadatos, EstadoImagen.pendiente_subida, fila.s3_key
                    cuentas["actualizadas"] += 1
                await conexion.execute(
                    update(Imagen)
                    .where(Imagen.id == fila.id, Imagen.estado == EstadoImagen.pendiente_subida)
                    .values(**valores)
                )
                planes.append(_Plan(imagen.orden, fila.id, estado, clave))
            else:
                planes.append(_Plan(imagen.orden, fila.id, EstadoImagen(fila.estado), None))
                cuentas["sin_cambios"] += 1
        if nuevas:
            await conexion.execute(insert(Imagen).values(nuevas))
        await recalcular_estado(conexion, video_id)

    # 3. Firmar (fuera de la transacción).
    urls = await firmar_puts(almacen, [plan.clave for plan in planes if plan.clave], ajustes.presign_put_ttl_s)
    registrar(log, "imagenes_registradas", video_id=str(video_id), recibidas=len(imagenes), urls=len(urls), **cuentas)
    return ImagenesRegistradas(
        imagenes=[
            ImagenRegistrada(
                orden=plan.orden,
                id=plan.imagen_id,
                estado=plan.estado,
                subida=(
                    SubidaPut(
                        url=urls[plan.clave].url,
                        encabezados=dict(ENCABEZADOS_PUT),
                        expira_en=urls[plan.clave].expira_en,
                    )
                    if plan.clave
                    else None
                ),
            )
            for plan in planes
        ]
    )


async def completar_subida(motor: AsyncEngine, almacen: AlmacenS3 | None, *, video_id: uuid.UUID) -> SubidaCompletada:
    """`HEAD` de las fotos `pendiente_subida`; las que están pasan a `subida` (con `bytes` y `etag`). Fija
    `subida_completa_en` la primera vez, recalcula el estado y devuelve el conteo. Repetirlo es seguro. Un `HEAD` que
    falla por otra causa que «no está» deja la foto pendiente (evento `s3_fallido`). `AlmacenNoConfigurado` tras
    comprobar el video."""
    async with sesion.transaccion(motor) as conexion:
        await _exigir_video_activo(conexion, video_id)
        almacen = _exigir_almacen(almacen)
        pendientes = (
            await conexion.execute(
                select(Imagen.id, Imagen.s3_key).where(
                    Imagen.video_id == video_id, Imagen.estado == EstadoImagen.pendiente_subida
                )
            )
        ).all()
    vistas = await consultar_varios(almacen, [fila.s3_key for fila in pendientes])
    fallidas = _resumir_fallos(vistas, video_id)
    encontradas = 0
    async with sesion.transaccion(motor) as conexion:
        await _exigir_video_activo(conexion, video_id, bloquear=True)
        for fila in pendientes:
            objeto = vistas.get(fila.s3_key)
            if isinstance(objeto, ObjetoS3):
                resultado = await conexion.execute(
                    update(Imagen)
                    .where(Imagen.id == fila.id, Imagen.estado == EstadoImagen.pendiente_subida)
                    .values(**_valores_subida(objeto))
                )
                encontradas += resultado.rowcount
        await conexion.execute(
            update(Video)
            .where(Video.id == video_id, Video.subida_completa_en.is_(None))
            .values(subida_completa_en=func.now())
        )
        estado, conteo = await recalcular_estado(conexion, video_id)
    registrar(
        log,
        "subida_completada",
        video_id=str(video_id),
        comprobadas=len(pendientes),
        encontradas=encontradas,
        fallidas=fallidas,
        estado=str(estado),
        conteo=conteo.como_dict(),
    )
    return SubidaCompletada(id=video_id, estado=estado, conteo=ConteoFotos(**conteo.como_dict()))
