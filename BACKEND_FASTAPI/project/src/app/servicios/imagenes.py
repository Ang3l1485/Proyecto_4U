"""Administración de imágenes del dataset (BE-4.1, ARCHITECTURE §4.12, §5.5): `/v1/admin/images`.

- `listar(motor, almacen, ttl_s, *, video_id, lugar_id, estado, calidad, q, pagina, por_pagina)` → `Pagina[ImagenAdmin]`
  (sin las de videos `eliminado`; por video, el más reciente primero, y `orden`).
- `detalle(motor, almacen, ajustes, imagen_id)` → `ImagenDetalle` (con `video` y `vector` de la versión activa).
- `editar(motor, almacen, ajustes, *, usuario_id, imagen_id, cambios)` → `ImagenAdmin` (`imagen.editar`).
- `eliminar(motor, cola_purga, *, usuario_id, imagen_id)`: borra la fila (y en cascada sus vectores), anota
  `imagen.eliminar` y **encola `purgar_imagen` dentro de la misma transacción** (ADR-BE-20): si SQS falla, nada cambia.
- `reprocesar(motor, cola_ingesta, *, usuario_id, imagen_id)`: la foto vuelve a `subida` y se encola
  `reprocesar_imagen` en `ingesta` (también dentro de la transacción).
- `lote(motor, cola_purga, *, usuario_id, accion, ids, lugar_id)` → `LoteResultado`: cada id en su transacción.

Toda escritura bloquea primero el video y después la imagen (orden de §4.5). Una imagen de un video `eliminado` cuenta
como inexistente (`ImagenNoEncontrada` → 404).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clientes.s3 import AlmacenS3
from app.clientes.sqs import ColaSqs, FalloSqs
from app.config import Settings
from app.db import sesion
from app.db.modelos import Embedding, Imagen, Lugar, Video
from app.dominio.enumerados import CalidadImagen, EstadoImagen, EstadoVideo
from app.dominio.mensajes import cuerpo_purgar_imagen, cuerpo_reprocesar
from app.esquemas.comun import Pagina
from app.esquemas.videos import FallidaLote, ImagenAdmin, ImagenDetalle, LoteResultado, ReferenciaVideo, VectorImagen
from app.logs import obtener_logger, registrar
from app.servicios import auditoria
from app.servicios.videos import ColaNoConfigurada, _escapar_like, con_urls, enviar, imagen_de_fila

log = obtener_logger(__name__)

#: Campos de `PATCH /v1/admin/images/{id}`, en el orden de `detalle.cambios` de `imagen.editar`.
CAMPOS_EDITABLES = ("lat", "lng", "lugar_id", "calidad", "notas")
#: `codigo` de `fallidas` en `POST /v1/admin/images/lote`.
CODIGO_NO_ENCONTRADO = "NO_ENCONTRADO"
CODIGO_VALIDACION = "VALIDACION"
CODIGO_ERROR_INTERNO = "ERROR_INTERNO"


class ImagenNoEncontrada(Exception):
    """No existe o su video está `eliminado` → 404."""


class LugarNoExiste(Exception):
    """`lugar_id` que no es un lugar → 422 (`campo` = `lugar_id`)."""


class ImagenNoSubida(Exception):
    """`reprocesar` de una foto `pendiente_subida` → 409 IMAGEN_NO_SUBIDA."""


def _consulta() -> Any:
    return (
        select(
            *Imagen.__table__.c,
            Lugar.nombre.label("lugar_nombre"),
            Video.numero.label("video_numero"),
            Video.nombre.label("video_nombre"),
            Video.estado.label("video_estado"),
        )
        .join(Video, Video.id == Imagen.video_id)
        .outerjoin(Lugar, Lugar.id == Imagen.lugar_id)
    )


# --- Lecturas -----------------------------------------------------------------------------------------------------
async def listar(
    motor: AsyncEngine,
    almacen: AlmacenS3 | None,
    ttl_s: int,
    *,
    video_id: uuid.UUID | None = None,
    lugar_id: uuid.UUID | None = None,
    estado: EstadoImagen | None = None,
    calidad: CalidadImagen | None = None,
    q: str | None = None,
    pagina: int = 1,
    por_pagina: int = 24,
) -> Pagina[ImagenAdmin]:
    """`q` busca contenido (sin mayúsculas; `%`, `_` y `\\` literales) en el nombre del video **o** en `notas`."""
    filtros: list[Any] = [Video.estado != EstadoVideo.eliminado]
    if video_id is not None:
        filtros.append(Imagen.video_id == video_id)
    if lugar_id is not None:
        filtros.append(Imagen.lugar_id == lugar_id)
    if estado is not None:
        filtros.append(Imagen.estado == estado)
    if calidad is not None:
        filtros.append(Imagen.calidad == calidad)
    if q:
        patron = f"%{_escapar_like(q)}%"
        filtros.append(or_(Video.nombre.ilike(patron, escape="\\"), Imagen.notas.ilike(patron, escape="\\")))
    async with sesion.transaccion(motor) as conexion:
        contar = select(func.count()).select_from(Imagen).join(Video, Video.id == Imagen.video_id).where(*filtros)
        total = (await conexion.execute(contar)).scalar_one()
        filas = await conexion.execute(
            _consulta()
            .where(*filtros)
            .order_by(Video.creado_en.desc(), Video.numero.desc(), Imagen.orden.asc())
            .limit(por_pagina)
            .offset((pagina - 1) * por_pagina)
        )
        items = [imagen_de_fila(fila) for fila in filas]
    items = await con_urls(items, almacen, ttl_s)
    return Pagina[ImagenAdmin](items=items, total=total, pagina=pagina, por_pagina=por_pagina)


async def _leer(conexion: AsyncConnection, imagen_id: uuid.UUID) -> Any:
    fila = (await conexion.execute(_consulta().where(Imagen.id == imagen_id))).first()
    if fila is None or fila.video_estado == EstadoVideo.eliminado:
        raise ImagenNoEncontrada(str(imagen_id))
    return fila


async def detalle(
    motor: AsyncEngine, almacen: AlmacenS3 | None, ajustes: Settings, imagen_id: uuid.UUID
) -> ImagenDetalle:
    async with sesion.transaccion(motor) as conexion:
        fila = await _leer(conexion, imagen_id)
        consulta = select(Embedding.version_vector, Embedding.creado_en).where(
            Embedding.imagen_id == imagen_id, Embedding.version_vector == ajustes.embedding_version_vector
        )
        vector = (await conexion.execute(consulta)).first()
    [imagen] = await con_urls([imagen_de_fila(fila)], almacen, ajustes.presign_get_ttl_s)
    return ImagenDetalle(
        **imagen.model_dump(),
        video=ReferenciaVideo(id=fila.video_id, numero=fila.video_numero, nombre=fila.video_nombre),
        vector=VectorImagen(version_vector=vector.version_vector, creado_en=vector.creado_en) if vector else None,
    )


# --- Escrituras ---------------------------------------------------------------------------------------------------
async def _bloquear(conexion: AsyncConnection, imagen_id: uuid.UUID) -> Any:
    """Orden video → imagen: lee el `video_id` sin bloqueo, bloquea el video y después la imagen (`FOR UPDATE`).
    `ImagenNoEncontrada` si no existe, si se movió o si el video está `eliminado`."""
    from app.servicios import recoleccion

    video_id = (await conexion.execute(select(Imagen.video_id).where(Imagen.id == imagen_id))).scalar_one_or_none()
    if video_id is None:
        raise ImagenNoEncontrada(str(imagen_id))
    estado = await recoleccion.bloquear_video(conexion, video_id)
    if estado is None or estado == EstadoVideo.eliminado:
        raise ImagenNoEncontrada(str(imagen_id))
    consulta = select(*Imagen.__table__.c).where(Imagen.id == imagen_id, Imagen.video_id == video_id).with_for_update()
    fila = (await conexion.execute(consulta)).first()
    if fila is None:
        raise ImagenNoEncontrada(str(imagen_id))
    return fila


async def _exigir_lugar(conexion: AsyncConnection, lugar_id: uuid.UUID | None) -> None:
    if lugar_id is not None and not (await conexion.execute(select(exists().where(Lugar.id == lugar_id)))).scalar():
        raise LugarNoExiste(str(lugar_id))


def _distinto(fila: Any, campo: str, valor: Any) -> bool:
    actual = getattr(fila, campo)
    if campo == "calidad":
        return str(actual) != str(valor)
    return actual != valor


async def _editar(
    motor: AsyncEngine, *, usuario_id: uuid.UUID, imagen_id: uuid.UUID, cambios: Mapping[str, Any], origen: str
) -> list[str]:
    """Aplica `cambios` (claves de `CAMPOS_EDITABLES`) y devuelve los campos que cambiaron (sin cambios no escribe)."""
    try:
        async with sesion.transaccion(motor) as conexion:
            fila = await _bloquear(conexion, imagen_id)
            if "lugar_id" in cambios:
                await _exigir_lugar(conexion, cambios["lugar_id"])
            distintos = [c for c in CAMPOS_EDITABLES if c in cambios and _distinto(fila, c, cambios[c])]
            if distintos:
                valores = {c: cambios[c] for c in distintos}
                await conexion.execute(
                    update(Imagen).where(Imagen.id == imagen_id).values(**valores, actualizado_en=func.now())
                )
                await auditoria.anotar(
                    conexion,
                    accion="imagen.editar",
                    entidad="imagen",
                    entidad_id=imagen_id,
                    actor_id=usuario_id,
                    detalle={"cambios": distintos, "video_id": str(fila.video_id), "origen": origen},
                )
    except IntegrityError as exc:  # el lugar se borró entre la comprobación y el UPDATE (FK, 23503)
        if "lugar_id" in cambios:
            raise LugarNoExiste(str(cambios["lugar_id"])) from exc
        raise
    if distintos:
        registrar(log, "imagen_editada", imagen_id=str(imagen_id), cambios=distintos, origen=origen)
    return distintos


async def editar(
    motor: AsyncEngine,
    almacen: AlmacenS3 | None,
    ajustes: Settings,
    *,
    usuario_id: uuid.UUID,
    imagen_id: uuid.UUID,
    cambios: Mapping[str, Any],
) -> ImagenAdmin:
    """`PATCH /v1/admin/images/{id}`. Cambiar la coordenada no toca el vector (solo depende de los píxeles)."""
    await _editar(motor, usuario_id=usuario_id, imagen_id=imagen_id, cambios=cambios, origen="patch")
    async with sesion.transaccion(motor) as conexion:
        fila = await _leer(conexion, imagen_id)
    [imagen] = await con_urls([imagen_de_fila(fila)], almacen, ajustes.presign_get_ttl_s)
    return imagen


async def eliminar(
    motor: AsyncEngine, cola: ColaSqs | None, *, usuario_id: uuid.UUID, imagen_id: uuid.UUID, origen: str = "delete"
) -> None:
    """`DELETE /v1/admin/images/{id}`. En una transacción: borra la fila (y en cascada sus vectores: sale de la búsqueda
    al confirmar), anota `imagen.eliminar`, recalcula el estado del video y envía `purgar_imagen` a `purga` **antes de
    confirmar**: si SQS falla (`FalloSqs`) se deshace todo. Si el `COMMIT` fallara después de enviar, el `worker`
    encuentra la fila y descarta el mensaje (ADR-BE-20)."""
    from app.servicios import recoleccion

    async with sesion.transaccion(motor) as conexion:
        fila = await _bloquear(conexion, imagen_id)
        if cola is None:
            raise ColaNoConfigurada("SQS_URL_PURGA")
        await conexion.execute(delete(Imagen).where(Imagen.id == imagen_id))
        await auditoria.anotar(
            conexion,
            accion="imagen.eliminar",
            entidad="imagen",
            entidad_id=imagen_id,
            actor_id=usuario_id,
            detalle={"video_id": str(fila.video_id), "orden": fila.orden, "estado": str(fila.estado), "origen": origen},
        )
        await recoleccion.recalcular_estado(conexion, fila.video_id)
        await enviar(cola, cuerpo_purgar_imagen(imagen_id, fila.video_id, usuario_id))
    registrar(log, "imagen_eliminada", imagen_id=str(imagen_id), video_id=str(fila.video_id), origen=origen)


async def reprocesar(motor: AsyncEngine, cola: ColaSqs | None, *, usuario_id: uuid.UUID, imagen_id: uuid.UUID) -> None:
    """`POST /v1/admin/images/{id}/reprocesar`: la foto pasa a `subida` (`error = NULL`; el vector actual sigue en la
    búsqueda hasta que el `worker` lo renueve, o lo borra si queda en `error`), se anota `imagen.reprocesar`, se
    recalcula el estado del video y se envía `reprocesar_imagen` a `ingesta` antes de confirmar.
    `ImagenNoSubida` si está `pendiente_subida` (no hay objeto que procesar)."""
    from app.servicios import recoleccion

    async with sesion.transaccion(motor) as conexion:
        fila = await _bloquear(conexion, imagen_id)
        if fila.estado == EstadoImagen.pendiente_subida:
            raise ImagenNoSubida(str(imagen_id))
        if cola is None:
            raise ColaNoConfigurada("SQS_URL_INGESTA")
        await conexion.execute(
            update(Imagen)
            .where(Imagen.id == imagen_id)
            .values(estado=EstadoImagen.subida, error=None, actualizado_en=func.now())
        )
        await auditoria.anotar(
            conexion,
            accion="imagen.reprocesar",
            entidad="imagen",
            entidad_id=imagen_id,
            actor_id=usuario_id,
            detalle={"video_id": str(fila.video_id), "estado_anterior": str(fila.estado)},
        )
        await recoleccion.recalcular_estado(conexion, fila.video_id)
        await enviar(cola, cuerpo_reprocesar(imagen_id, usuario_id))
    registrar(log, "imagen_reprocesada", imagen_id=str(imagen_id), video_id=str(fila.video_id))


async def lote(
    motor: AsyncEngine,
    cola: ColaSqs | None,
    *,
    usuario_id: uuid.UUID,
    accion: str,
    ids: Sequence[uuid.UUID],
    lugar_id: uuid.UUID | None = None,
) -> LoteResultado:
    """`POST /v1/admin/images/lote`. Ids repetidos cuentan una vez. Antes de empezar: `ColaNoConfigurada` (eliminar)
    o `LugarNoExiste` (reasignar a un lugar que no existe): nada se aplica. Después, cada id en su propia transacción y
    en orden; un id que no existe (o de un video eliminado) va a `fallidas` con `NO_ENCONTRADO`; SQS que falla al
    eliminar, con `ERROR_INTERNO` (esa imagen no cambia). Un fallo de la base corta el lote (`BaseNoDisponible` → 503):
    lo ya aplicado queda y repetir es seguro (eliminar lo ya borrado da `NO_ENCONTRADO`; reasignar es idempotente)."""
    if accion == "eliminar" and cola is None:
        raise ColaNoConfigurada("SQS_URL_PURGA")
    if accion == "reasignar":
        async with sesion.transaccion(motor) as conexion:
            await _exigir_lugar(conexion, lugar_id)
    procesadas = 0
    fallidas: list[FallidaLote] = []
    for imagen_id in dict.fromkeys(ids):
        try:
            if accion == "eliminar":
                await eliminar(motor, cola, usuario_id=usuario_id, imagen_id=imagen_id, origen="lote")
            else:
                await _editar(
                    motor, usuario_id=usuario_id, imagen_id=imagen_id, cambios={"lugar_id": lugar_id}, origen="lote"
                )
            procesadas += 1
        except ImagenNoEncontrada:
            fallidas.append(FallidaLote(id=imagen_id, codigo=CODIGO_NO_ENCONTRADO))
        except LugarNoExiste:
            fallidas.append(FallidaLote(id=imagen_id, codigo=CODIGO_VALIDACION))
        except FalloSqs as exc:
            registrar(log, "cola_fallida", logging.ERROR, cola="purga", operacion="enviar", motivo=str(exc))
            fallidas.append(FallidaLote(id=imagen_id, codigo=CODIGO_ERROR_INTERNO))
    registrar(log, "imagenes_lote", accion=accion, pedidas=len(ids), procesadas=procesadas, fallidas=len(fallidas))
    return LoteResultado(procesadas=procesadas, fallidas=fallidas)
