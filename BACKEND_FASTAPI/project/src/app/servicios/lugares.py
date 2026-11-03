"""Lugares (ARCHITECTURE §4.9, §5.3 `GET /v1/places`, §5.5 `/v1/admin/places`), BE-3.1.

- `listar_publico(motor, *, lat=None, lng=None, categoria=None)` → `list[LugarPublico]`: con posición, por distancia
  (la de `geo.distancia_m`, sin redondear) y a igualdad por `nombre_normalizado` e `id`; sin posición, por
  `nombre_normalizado` e `id`. El orden de los nombres es el de los puntos de código (como `COLLATE "C"`), no la
  intercalación de la base: se ordena en Python.
- `listar_admin(motor, *, q=None, categoria=None)` → `list[LugarAdmin]` (orden por nombre, como arriba); `q` se
  normaliza como un nombre y se busca contenido en `nombre_normalizado` (`%`, `_` y `\\` literales).
- `crear(motor, *, usuario_id, datos)` → `LugarAdmin`; `reemplazar(motor, *, usuario_id, lugar_id, datos)` →
  `LugarAdmin`; `borrar(motor, *, usuario_id, lugar_id)` → `Borrado(existia, fotos_sin_lugar)`. Cada cambio deja su
  fila de `auditoria` (`lugar.crear`, `lugar.editar`, `lugar.eliminar`, §5.7) en la misma transacción.
- Excepciones: `NombreDuplicado` (→ `409 NOMBRE_DUPLICADO`) y `LugarNoEncontrado` (→ `404`, solo en `reemplazar`).
- `leer_todos(conexion, categoria=None)` → `list[LugarRef]`, dentro de una transacción abierta (para BE-3.2, §4.10).

Orden de bloqueo de `borrar`: los videos de las fotos del lugar (por id, `recoleccion.bloquear_video`) → el lugar
(`FOR UPDATE`) → las fotos. Así respeta el «video → imágenes» de §4.5 y no se cruza con una edición de imagen de BE-4.1
(video → imagen → `KEY SHARE` del lugar por la FK). `reemplazar` solo bloquea el lugar con `FOR NO KEY UPDATE`, que no
choca con ese `KEY SHARE`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import sesion
from app.db.modelos import Imagen, Lugar, Video
from app.dominio import geo
from app.dominio.enumerados import CategoriaLugar, EstadoVideo
from app.dominio.lugares import DECIMALES_DISTANCIA, normalizar_nombre
from app.esquemas.lugares import LugarAdmin, LugarEntrada, LugarPublico
from app.logs import obtener_logger, registrar
from app.servicios import auditoria
from app.servicios.recoleccion import bloquear_video

log = obtener_logger(__name__)

RESTRICCION_NOMBRE = "lugares_nombre_normalizado_key"
#: Campos de `LugarEntrada` que guarda la tabla (los que lista `detalle.cambios` de `lugar.editar`).
CAMPOS = ("nombre", "categoria", "lat", "lng", "alias", "descripcion", "referencias")
_COLUMNAS = tuple(Lugar.__table__.c)


class LugarNoEncontrado(Exception):
    """No existe un lugar con ese id."""


class NombreDuplicado(Exception):
    """Otro lugar tiene el mismo `nombre_normalizado`."""


@dataclass(frozen=True)
class LugarRef:
    """Lo que necesita la localización (BE-3.2) de cada lugar."""

    id: uuid.UUID
    nombre: str
    categoria: CategoriaLugar
    lat: float
    lng: float


@dataclass(frozen=True)
class Borrado:
    existia: bool
    fotos_sin_lugar: int


# --- Conversión ---------------------------------------------------------------------------------------------------
def _imagen_url(fila: Any) -> str | None:
    """Siempre `None`: ningún endpoint sube todavía la foto de un lugar (`imagen_key` queda nulo, §5.3)."""
    return None


def _comunes(fila: Any) -> dict[str, Any]:
    return {
        "id": fila.id,
        "nombre": fila.nombre,
        "categoria": fila.categoria,
        "lat": fila.lat,
        "lng": fila.lng,
        "alias": list(fila.alias or []),
        "descripcion": fila.descripcion,
        "referencias": fila.referencias,
        "imagen_url": _imagen_url(fila),
    }


def _admin(fila: Any, total_fotos: int) -> LugarAdmin:
    return LugarAdmin(
        **_comunes(fila), creado_en=fila.creado_en, actualizado_en=fila.actualizado_en, total_fotos=total_fotos
    )


def _orden_nombre(fila: Any) -> tuple[str, str]:
    return (fila.nombre_normalizado, str(fila.id))


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _es_nombre_duplicado(exc: BaseException) -> bool:
    """¿Un `IntegrityError` por `lugares_nombre_normalizado_key`? Mira `constraint_name` en la cadena de causas
    (asyncpg) y, si no, el texto del error (sin parámetros: los motores usan `hide_parameters`)."""
    vistos: set[int] = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in vistos:
        vistos.add(id(actual))
        if getattr(actual, "constraint_name", None) == RESTRICCION_NOMBRE:
            return True
        actual = getattr(actual, "orig", None) or actual.__cause__
    return RESTRICCION_NOMBRE in str(getattr(exc, "orig", exc))


def _consulta_fotos():
    """Fotos por lugar: imágenes con `lugar_id` de videos no eliminados, en cualquier estado."""
    return (
        select(Imagen.lugar_id.label("lugar_id"), func.count().label("n"))
        .join(Video, Video.id == Imagen.video_id)
        .where(Imagen.lugar_id.is_not(None), Video.estado != EstadoVideo.eliminado)
        .group_by(Imagen.lugar_id)
    )


async def _total_fotos(conexion: AsyncConnection, lugar_id: uuid.UUID) -> int:
    consulta = _consulta_fotos().where(Imagen.lugar_id == lugar_id)
    fila = (await conexion.execute(consulta)).first()
    return int(fila.n) if fila is not None else 0


# --- Lectura ------------------------------------------------------------------------------------------------------
async def leer_todos(conexion: AsyncConnection, categoria: CategoriaLugar | None = None) -> list[LugarRef]:
    """Todos los lugares (o los de una categoría), ordenados por nombre normalizado e id."""
    consulta = select(Lugar.id, Lugar.nombre, Lugar.nombre_normalizado, Lugar.categoria, Lugar.lat, Lugar.lng)
    if categoria is not None:
        consulta = consulta.where(Lugar.categoria == categoria)
    filas = sorted((await conexion.execute(consulta)).all(), key=_orden_nombre)
    return [LugarRef(id=f.id, nombre=f.nombre, categoria=f.categoria, lat=f.lat, lng=f.lng) for f in filas]


async def listar_publico(
    motor: AsyncEngine,
    *,
    lat: float | None = None,
    lng: float | None = None,
    categoria: CategoriaLugar | None = None,
) -> list[LugarPublico]:
    consulta = select(*_COLUMNAS)
    if categoria is not None:
        consulta = consulta.where(Lugar.categoria == categoria)
    async with sesion.transaccion(motor) as conexion:
        filas: Sequence[Any] = (await conexion.execute(consulta)).all()
    if lat is None or lng is None:
        return [LugarPublico(**_comunes(f), distancia_m=None) for f in sorted(filas, key=_orden_nombre)]
    con_distancia = sorted(
        ((geo.distancia_m(lat, lng, f.lat, f.lng), f) for f in filas),
        key=lambda par: (par[0], *_orden_nombre(par[1])),
    )
    return [
        LugarPublico(**_comunes(f), distancia_m=round(distancia, DECIMALES_DISTANCIA)) for distancia, f in con_distancia
    ]


async def listar_admin(
    motor: AsyncEngine, *, q: str | None = None, categoria: CategoriaLugar | None = None
) -> list[LugarAdmin]:
    fotos = _consulta_fotos().subquery("fotos")
    consulta = select(*_COLUMNAS, func.coalesce(fotos.c.n, 0).label("total_fotos")).outerjoin(
        fotos, fotos.c.lugar_id == Lugar.id
    )
    if categoria is not None:
        consulta = consulta.where(Lugar.categoria == categoria)
    texto = normalizar_nombre(q) if q is not None else ""
    if texto:
        consulta = consulta.where(Lugar.nombre_normalizado.like(f"%{_escapar_like(texto)}%", escape="\\"))
    async with sesion.transaccion(motor) as conexion:
        filas = (await conexion.execute(consulta)).all()
    return [_admin(f, int(f.total_fotos)) for f in sorted(filas, key=_orden_nombre)]


# --- Escritura ----------------------------------------------------------------------------------------------------
def _valores(datos: LugarEntrada) -> dict[str, Any]:
    return {
        "nombre": datos.nombre,
        "categoria": datos.categoria,
        "lat": datos.lat,
        "lng": datos.lng,
        "alias": list(datos.alias or []),
        "descripcion": datos.descripcion,
        "referencias": datos.referencias,
    }


async def crear(motor: AsyncEngine, *, usuario_id: uuid.UUID, datos: LugarEntrada) -> LugarAdmin:
    valores = _valores(datos)
    insercion = (
        pg_insert(Lugar)
        .values(**valores, nombre_normalizado=normalizar_nombre(datos.nombre), creado_por=usuario_id)
        .on_conflict_do_nothing(constraint=RESTRICCION_NOMBRE)
        .returning(*_COLUMNAS)
    )
    async with sesion.transaccion(motor) as conexion:
        fila = (await conexion.execute(insercion)).first()
        if fila is None:
            raise NombreDuplicado(datos.nombre)
        await auditoria.anotar(
            conexion,
            accion="lugar.crear",
            entidad="lugar",
            entidad_id=fila.id,
            actor_id=usuario_id,
            detalle={"nombre": fila.nombre, "categoria": str(fila.categoria)},
        )
    registrar(log, "lugar_guardado", logging.INFO, operacion="crear", lugar_id=str(fila.id), cambios=list(CAMPOS))
    return _admin(fila, 0)


async def reemplazar(
    motor: AsyncEngine, *, usuario_id: uuid.UUID, lugar_id: uuid.UUID, datos: LugarEntrada
) -> LugarAdmin:
    valores = _valores(datos)
    normalizado = normalizar_nombre(datos.nombre)
    try:
        async with sesion.transaccion(motor) as conexion:
            consulta = select(*_COLUMNAS).where(Lugar.id == lugar_id).with_for_update(key_share=True)
            actual = (await conexion.execute(consulta)).first()
            if actual is None:
                raise LugarNoEncontrado(str(lugar_id))
            cambios = [campo for campo in CAMPOS if _distinto(getattr(actual, campo), valores[campo])]
            fila = actual
            if cambios:
                if normalizado != actual.nombre_normalizado:
                    otro = select(Lugar.id).where(Lugar.nombre_normalizado == normalizado, Lugar.id != lugar_id)
                    if (await conexion.execute(otro)).first() is not None:
                        raise NombreDuplicado(datos.nombre)
                cambio = (
                    update(Lugar)
                    .where(Lugar.id == lugar_id)
                    .values(**valores, nombre_normalizado=normalizado, actualizado_en=func.now())
                    .returning(*_COLUMNAS)
                )
                fila = (await conexion.execute(cambio)).one()
                await auditoria.anotar(
                    conexion,
                    accion="lugar.editar",
                    entidad="lugar",
                    entidad_id=lugar_id,
                    actor_id=usuario_id,
                    detalle={"cambios": cambios},
                )
            total = await _total_fotos(conexion, lugar_id)
    except IntegrityError as exc:
        if _es_nombre_duplicado(exc):
            raise NombreDuplicado(datos.nombre) from None
        raise
    if cambios:
        registrar(log, "lugar_guardado", logging.INFO, operacion="editar", lugar_id=str(lugar_id), cambios=cambios)
    return _admin(fila, total)


def _distinto(guardado: Any, nuevo: Any) -> bool:
    if isinstance(guardado, list) or isinstance(nuevo, list):
        return list(guardado or []) != list(nuevo or [])
    return guardado != nuevo


async def borrar(motor: AsyncEngine, *, usuario_id: uuid.UUID, lugar_id: uuid.UUID) -> Borrado:
    async with sesion.transaccion(motor) as conexion:
        videos = (
            await conexion.execute(select(Imagen.video_id).where(Imagen.lugar_id == lugar_id).distinct())
        ).scalars()
        for video_id in sorted(videos, key=str):
            await bloquear_video(conexion, video_id)
        actual = (
            await conexion.execute(select(Lugar.id, Lugar.nombre).where(Lugar.id == lugar_id).with_for_update())
        ).first()
        if actual is None:
            resultado = Borrado(existia=False, fotos_sin_lugar=0)
        else:
            sin_lugar = await conexion.execute(
                update(Imagen).where(Imagen.lugar_id == lugar_id).values(lugar_id=None, actualizado_en=func.now())
            )
            await conexion.execute(delete(Lugar).where(Lugar.id == lugar_id))
            resultado = Borrado(existia=True, fotos_sin_lugar=sin_lugar.rowcount or 0)
            await auditoria.anotar(
                conexion,
                accion="lugar.eliminar",
                entidad="lugar",
                entidad_id=lugar_id,
                actor_id=usuario_id,
                detalle={"nombre": actual.nombre, "fotos_sin_lugar": resultado.fotos_sin_lugar},
            )
    registrar(
        log,
        "lugar_eliminado",
        logging.INFO,
        lugar_id=str(lugar_id),
        existia=resultado.existia,
        fotos_sin_lugar=resultado.fotos_sin_lugar,
    )
    return resultado
