"""Lectura de videos para el panel (ARCHITECTURE §4.5, §5.5): `GET /v1/admin/videos` y `GET /v1/admin/videos/{id}`.

BE-2.1 entrega las dos lecturas; BE-4.1 añade renombrar y borrar (ADR-BE-07, ADR-BE-20) y las URLs GET de las fotos.
Los videos `eliminado` no aparecen en el listado y su detalle es `VideoNoEncontrado` (→ 404, §5.6).

- `listar(motor, q=, orden=, direccion=, pagina=, por_pagina=)` → `Pagina[VideoResumen]`.
- `detalle(motor, video_id, almacen=None, ttl_s=3600)` → `VideoDetalle` (fotos en `orden`, con `lugar` y, con
  `almacen`, sus URLs GET: `con_urls`).
- `renombrar(motor, usuario_id=, video_id=, nombre=)` → `VideoResumen`; `borrar(motor, cola, usuario_id=, video_id=)` →
  `VideoBorrado` (BE-4.1).
- `resumen(conexion, video_id)` → `VideoResumen | None` dentro de una transacción ya abierta (lo usa la recolección).
- `contar(conexion, video_id)` → `Conteo` (fotos por estado).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

import anyio.to_thread
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clientes import s3
from app.clientes.s3 import AlmacenS3, FalloS3
from app.clientes.sqs import ColaSqs, FalloSqs
from app.db import sesion
from app.db.modelos import Auditoria, Embedding, Imagen, Lugar, Usuario, Video
from app.dominio.enumerados import EstadoImagen, EstadoVideo
from app.dominio.mensajes import cuerpo_purgar_video
from app.dominio.recoleccion import Conteo, clave_dataset, clave_miniatura, real_legible
from app.esquemas.comun import Pagina, Referencia
from app.esquemas.videos import (
    ConteoFotos,
    ImagenAdmin,
    InicioRecorrido,
    VideoBorrado,
    VideoDetalle,
    VideoResumen,
)
from app.logs import obtener_logger, registrar
from app.servicios import auditoria

log = obtener_logger(__name__)

OrdenVideos = Literal["fecha", "nombre", "fotos"]
Direccion = Literal["desc", "asc"]


class VideoNoEncontrado(Exception):
    """No existe (o, en las lecturas, está `eliminado`)."""


class VideoEliminado(Exception):
    """Existe pero está `eliminado` (en las escrituras de recolección → 409 VIDEO_ELIMINADO)."""


class ColaNoConfigurada(Exception):
    """BE-4.1: falta la cola a la que hay que enviar (`SQS_URL_PURGA` o `SQS_URL_INGESTA` en `api`) → 500. Se lanza
    antes de escribir nada."""

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"falta {variable}")


async def enviar(cola: ColaSqs, cuerpo: str) -> str:
    """`cola.enviar(cuerpo)` en un hilo (boto3 es síncrono). `FalloSqs` si SQS no lo acepta."""
    return await anyio.to_thread.run_sync(cola.enviar, cuerpo)


# --- Consultas ----------------------------------------------------------------------------------------------------
def _subconsulta_conteo():
    def contar_estado(estado: EstadoImagen):
        return func.count().filter(Imagen.estado == estado).label(estado.value)

    return (
        select(
            Imagen.video_id.label("video_id"),
            *(contar_estado(estado) for estado in EstadoImagen),
            func.count().label("total"),
        )
        .group_by(Imagen.video_id)
        .subquery("conteo")
    )


def _consulta_resumen(conteo: Any):
    return (
        select(
            *Video.__table__.c,
            Usuario.nombre.label("creador_nombre"),
            *(func.coalesce(conteo.c[estado.value], 0).label(f"n_{estado.value}") for estado in EstadoImagen),
        )
        .join(Usuario, Usuario.id == Video.creado_por)
        .outerjoin(conteo, conteo.c.video_id == Video.id)
    )


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conteo_de_fila(fila: Any) -> ConteoFotos:
    return ConteoFotos(**{estado.value: int(getattr(fila, f"n_{estado.value}")) for estado in EstadoImagen})


def resumen_de_fila(fila: Any) -> VideoResumen:
    """Fila de `_consulta_resumen` → `VideoResumen` (los `real` con su valor legible, §5.5)."""
    inicio = None
    if fila.inicio_lat is not None and fila.inicio_lng is not None:
        inicio = InicioRecorrido(lat=fila.inicio_lat, lng=fila.inicio_lng, rumbo=real_legible(fila.inicio_rumbo))
    return VideoResumen(
        id=fila.id,
        numero=fila.numero,
        nombre=fila.nombre,
        ref_cliente=fila.ref_cliente,
        estado=fila.estado,
        creado_en=fila.creado_en,
        iniciado_en=fila.iniciado_en,
        finalizado_en=fila.finalizado_en,
        duracion_s=fila.duracion_s,
        distancia_m=real_legible(fila.distancia_m),
        pasos=fila.pasos,
        inicio=inicio,
        total_fotos=fila.total_fotos_declaradas,
        conteo=_conteo_de_fila(fila),
        creado_por=Referencia(id=fila.creado_por, nombre=fila.creador_nombre),
    )


async def contar(conexion: AsyncConnection, video_id: uuid.UUID) -> Conteo:
    filas = await conexion.execute(
        select(Imagen.estado, func.count()).where(Imagen.video_id == video_id).group_by(Imagen.estado)
    )
    return Conteo.desde({str(estado): n for estado, n in filas})


async def resumen(conexion: AsyncConnection, video_id: uuid.UUID) -> VideoResumen | None:
    """`VideoResumen` del video (también si está `eliminado`), o `None` si no existe."""
    fila = (await conexion.execute(_consulta_resumen(_subconsulta_conteo()).where(Video.id == video_id))).first()
    return resumen_de_fila(fila) if fila is not None else None


# --- Casos de uso -------------------------------------------------------------------------------------------------
async def listar(
    motor: AsyncEngine,
    *,
    q: str | None = None,
    orden: OrdenVideos = "fecha",
    direccion: Direccion = "desc",
    pagina: int = 1,
    por_pagina: int = 24,
) -> Pagina[VideoResumen]:
    """Videos no eliminados; `q` filtra por `nombre` (contiene, sin distinguir mayúsculas; `%` y `_` son literales).
    `orden`: `fecha` (`creado_en`), `nombre` (en minúsculas) o `fotos` (fotos registradas); desempata `numero`."""
    conteo = _subconsulta_conteo()
    filtros = [Video.estado != EstadoVideo.eliminado]
    if q:
        filtros.append(Video.nombre.ilike(f"%{_escapar_like(q)}%", escape="\\"))
    columna = {
        "fecha": Video.creado_en,
        "nombre": func.lower(Video.nombre),
        "fotos": func.coalesce(conteo.c.total, 0),
    }[orden]
    criterio = [columna.desc(), Video.numero.desc()] if direccion == "desc" else [columna.asc(), Video.numero.asc()]
    async with sesion.transaccion(motor) as conexion:
        total = (await conexion.execute(select(func.count()).select_from(Video).where(*filtros))).scalar_one()
        filas = await conexion.execute(
            _consulta_resumen(conteo)
            .where(*filtros)
            .order_by(*criterio)
            .limit(por_pagina)
            .offset((pagina - 1) * por_pagina)
        )
        items = [resumen_de_fila(fila) for fila in filas]
    return Pagina[VideoResumen](items=items, total=total, pagina=pagina, por_pagina=por_pagina)


def imagen_de_fila(foto: Any) -> ImagenAdmin:
    """Fila con las columnas de `imagenes` y `lugar_nombre` → `ImagenAdmin` (sin URLs: `con_urls`)."""
    return ImagenAdmin(
        id=foto.id,
        video_id=foto.video_id,
        orden=foto.orden,
        lat=foto.lat,
        lng=foto.lng,
        rumbo=real_legible(foto.rumbo),
        capturada_en=foto.capturada_en,
        estado=foto.estado,
        error=foto.error,
        calidad=foto.calidad,
        lugar=Referencia(id=foto.lugar_id, nombre=foto.lugar_nombre) if foto.lugar_id is not None else None,
        notas=foto.notas,
    )


def _claves_de(foto: ImagenAdmin) -> tuple[str | None, str | None]:
    """(original, miniatura) que se firman: el original si la foto no está `pendiente_subida`; la miniatura solo si
    está `procesada` (el `worker` la escribe al procesarla)."""
    original = clave_dataset(foto.video_id, foto.id) if foto.estado != EstadoImagen.pendiente_subida else None
    miniatura = clave_miniatura(foto.video_id, foto.id) if foto.estado == EstadoImagen.procesada else None
    return original, miniatura


async def con_urls[T: ImagenAdmin](imagenes: list[T], almacen: AlmacenS3 | None, ttl_s: int) -> list[T]:
    """BE-4.1: rellena `url`, `url_miniatura` (reglas de `_claves_de`) y `url_expira_en` (el vencimiento más temprano
    de las dos; se firman todas juntas). Sin `almacen`, o si la firma falla (`s3_fallido` `WARNING`), las deja en
    `null`: el detalle sigue respondiendo (lo usa la barra de progreso de la app)."""
    if almacen is None or not imagenes:
        return imagenes
    claves = [clave for foto in imagenes for clave in _claves_de(foto) if clave is not None]
    if not claves:
        return imagenes
    try:
        firmadas = await s3.firmar_gets(almacen, claves, ttl_s)
    except FalloS3 as exc:
        registrar(log, "s3_fallido", logging.WARNING, operacion="firmar_get", motivo=str(exc))
        return imagenes
    resultado = []
    for foto in imagenes:
        clave_original, clave_miniatura_ = _claves_de(foto)
        original = firmadas.get(clave_original) if clave_original else None
        miniatura = firmadas.get(clave_miniatura_) if clave_miniatura_ else None
        vencimientos = [u.expira_en for u in (original, miniatura) if u is not None]
        resultado.append(
            foto.model_copy(
                update={
                    "url": original.url if original else None,
                    "url_miniatura": miniatura.url if miniatura else None,
                    "url_expira_en": min(vencimientos) if vencimientos else None,
                }
            )
        )
    return resultado


async def detalle(
    motor: AsyncEngine, video_id: uuid.UUID, *, almacen: AlmacenS3 | None = None, ttl_s: int = 3600
) -> VideoDetalle:
    """`VideoResumen` + `fotos` en `orden` (con URLs GET si hay `almacen`). `VideoNoEncontrado` si no existe o está
    `eliminado`."""
    async with sesion.transaccion(motor) as conexion:
        fila = (await conexion.execute(_consulta_resumen(_subconsulta_conteo()).where(Video.id == video_id))).first()
        if fila is None or fila.estado == EstadoVideo.eliminado:
            raise VideoNoEncontrado(str(video_id))
        fotos = await conexion.execute(
            select(*Imagen.__table__.c, Lugar.nombre.label("lugar_nombre"))
            .outerjoin(Lugar, Lugar.id == Imagen.lugar_id)
            .where(Imagen.video_id == video_id)
            .order_by(Imagen.orden)
        )
        imagenes = [imagen_de_fila(foto) for foto in fotos]
    imagenes = await con_urls(imagenes, almacen, ttl_s)
    return VideoDetalle(**resumen_de_fila(fila).model_dump(), fotos=imagenes)


async def renombrar(motor: AsyncEngine, *, usuario_id: uuid.UUID, video_id: uuid.UUID, nombre: str) -> VideoResumen:
    """`PATCH /v1/admin/videos/{id}` (BE-4.1). El mismo nombre no escribe (ni `actualizado_en` ni auditoría).
    `VideoNoEncontrado` si no existe o está `eliminado`."""
    async with sesion.transaccion(motor) as conexion:
        consulta = select(Video.nombre, Video.estado).where(Video.id == video_id).with_for_update()
        fila = (await conexion.execute(consulta)).first()
        if fila is None or fila.estado == EstadoVideo.eliminado:
            raise VideoNoEncontrado(str(video_id))
        cambiado = fila.nombre != nombre
        if cambiado:
            await conexion.execute(
                update(Video).where(Video.id == video_id).values(nombre=nombre, actualizado_en=func.now())
            )
            await auditoria.anotar(
                conexion,
                accion="video.renombrar",
                entidad="video",
                entidad_id=video_id,
                actor_id=usuario_id,
                detalle={"anterior": fila.nombre, "nuevo": nombre},
            )
        resultado = await resumen(conexion, video_id)
    registrar(log, "video_renombrado", video_id=str(video_id), cambiado=cambiado)
    if resultado is None:  # no puede pasar: el video estaba bloqueado
        raise VideoNoEncontrado(str(video_id))
    return resultado


async def _fotos_retiradas(conexion: AsyncConnection, video_id: uuid.UUID) -> int:
    """Lo que dijo el primer `DELETE` (fila `video.eliminar`); sin ella (un video borrado de otra forma), las fotos
    que quedan."""
    consulta = (
        select(Auditoria.detalle["fotos_retiradas"].as_integer())
        .where(Auditoria.accion == "video.eliminar", Auditoria.entidad_id == str(video_id))
        .order_by(Auditoria.id.desc())
        .limit(1)
    )
    guardado = (await conexion.execute(consulta)).scalar_one_or_none()
    if guardado is not None:
        return int(guardado)
    total = select(func.count()).select_from(Imagen).where(Imagen.video_id == video_id)
    return int((await conexion.execute(total)).scalar_one())


async def borrar(
    motor: AsyncEngine, cola: ColaSqs | None, *, usuario_id: uuid.UUID, video_id: uuid.UUID
) -> VideoBorrado:
    """`DELETE /v1/admin/videos/{id}` (BE-4.1, ADR-BE-07). En **una** transacción (video bloqueado, orden video →
    imágenes): borra los vectores de sus fotos (salen de la búsqueda al confirmar), marca el video `eliminado`
    (`eliminado_en`, `eliminado_por`) y anota `video.eliminar`. Después de confirmar, encola `purgar_video`; si SQS
    falla, `purga_no_encolada` (`WARNING`) y responde igual: el reconciliador lo reenvía (§4.12). Un video ya
    `eliminado` da la misma respuesta sin escribir ni encolar nada. `VideoNoEncontrado` si no existe;
    `ColaNoConfigurada` (sin escribir) si falta `SQS_URL_PURGA`."""
    from app.servicios import recoleccion  # recoleccion importa este módulo

    nuevo = False
    async with sesion.transaccion(motor) as conexion:
        estado = await recoleccion.bloquear_video(conexion, video_id)
        if estado is None:
            raise VideoNoEncontrado(str(video_id))
        if estado == EstadoVideo.eliminado:
            retiradas = await _fotos_retiradas(conexion, video_id)
        else:
            if cola is None:
                raise ColaNoConfigurada("SQS_URL_PURGA")
            nuevo = True
            de_video = select(Imagen.id).where(Imagen.video_id == video_id)
            total = select(func.count()).select_from(Imagen).where(Imagen.video_id == video_id)
            retiradas = int((await conexion.execute(total)).scalar_one())
            vectores = (await conexion.execute(delete(Embedding).where(Embedding.imagen_id.in_(de_video)))).rowcount
            marcar = (
                update(Video)
                .where(Video.id == video_id)
                .values(
                    estado=EstadoVideo.eliminado,
                    eliminado_en=func.now(),
                    eliminado_por=usuario_id,
                    actualizado_en=func.now(),
                )
                .returning(Video.nombre, Video.numero)
            )
            fila = (await conexion.execute(marcar)).one()
            await auditoria.anotar(
                conexion,
                accion="video.eliminar",
                entidad="video",
                entidad_id=video_id,
                actor_id=usuario_id,
                detalle={
                    "nombre": fila.nombre,
                    "numero": fila.numero,
                    "fotos_retiradas": retiradas,
                    "vectores": vectores or 0,
                },
            )
    encolada = None
    if nuevo and cola is not None:
        try:
            await enviar(cola, cuerpo_purgar_video(video_id, usuario_id))
            encolada = True
        except FalloSqs as exc:
            encolada = False
            registrar(log, "purga_no_encolada", logging.WARNING, video_id=str(video_id), motivo=str(exc))
    registrar(
        log, "video_eliminado", video_id=str(video_id), fotos_retiradas=retiradas, repetido=not nuevo, encolada=encolada
    )
    return VideoBorrado(id=video_id, fotos_retiradas=retiradas)
