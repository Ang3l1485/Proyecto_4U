"""`python -m app.cli limpiar-validacion` (ARCHITECTURE §4.5, §5.9): borrado definitivo de los videos de prueba.

Solo toca videos cuyo `nombre` **y** `ref_cliente` empiezan por `validacion-` (`es_dato_de_validacion`). Con
`video_ids` = `None` (sin `--video`) toma todos esos; con una lista, solo esos, y se niega entera (`LimpiezaRechazada`,
nada se borra) si alguno no existe o no lleva el prefijo. Una lista **vacía** no borra nada (nunca equivale a «todos»).

Orden: objetos de `dataset/{id}/` y `thumbs/{id}/` → filas (`videos`, y en cascada `imagenes` y `embeddings`) → otra
pasada por S3 (una miniatura que el `worker` escribiera entretanto). Si S3 falla en la primera pasada, las filas quedan
y repetir el comando termina el trabajo (`FalloS3`). Si falla en la segunda, ya sin filas, el comando no falla: el
resultado lleva `restos_s3` (prefijos que pudieron quedar con objetos huérfanos) y `motivo_restos`.

Con `simular=True` hace las mismas comprobaciones (y la misma negativa) y cuenta los objetos que borraría, sin borrar.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import anyio.to_thread
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clientes.s3 import AlmacenS3, FalloS3
from app.db import sesion
from app.db.modelos import Video
from app.dominio.recoleccion import PREFIJO_VALIDACION, es_dato_de_validacion, prefijos_del_video


@dataclass(frozen=True)
class ResultadoLimpieza:
    videos: int
    objetos: int
    video_ids: list[str] = field(default_factory=list)
    simulada: bool = False
    restos_s3: list[str] = field(default_factory=list)  # prefijos de la segunda pasada que no se pudieron borrar
    motivo_restos: str | None = None


class LimpiezaRechazada(Exception):
    """Algún id no existe o no es un video de validación: no se borra nada."""

    def __init__(self, inexistentes: list[str], sin_prefijo: list[str]) -> None:
        self.inexistentes = inexistentes
        self.sin_prefijo = sin_prefijo
        partes = []
        if inexistentes:
            partes.append(f"no existen: {', '.join(inexistentes)}")
        if sin_prefijo:
            partes.append(f"sin el prefijo {PREFIJO_VALIDACION} en nombre y ref_cliente: {', '.join(sin_prefijo)}")
        super().__init__("; ".join(partes))


def _es_de_validacion():
    return (
        Video.nombre.startswith(PREFIJO_VALIDACION, autoescape=True),
        Video.ref_cliente.startswith(PREFIJO_VALIDACION, autoescape=True),
    )


def _prefijos(video_ids: Sequence[uuid.UUID]) -> list[str]:
    return [prefijo for video_id in video_ids for prefijo in prefijos_del_video(video_id)]


def _borrar(almacen: AlmacenS3, prefijos: Sequence[str]) -> int:
    return sum(almacen.borrar_prefijo(prefijo) for prefijo in prefijos)


def _contar(almacen: AlmacenS3, prefijos: Sequence[str]) -> int:
    return sum(almacen.contar_prefijo(prefijo) for prefijo in prefijos)


def _segunda_pasada(almacen: AlmacenS3, prefijos: Sequence[str]) -> tuple[int, list[str], str | None]:
    borrados, restos, motivo = 0, [], None
    for prefijo in prefijos:
        try:
            borrados += almacen.borrar_prefijo(prefijo)
        except FalloS3 as exc:
            restos.append(prefijo)
            motivo = motivo or str(exc)
    return borrados, restos, motivo


async def limpiar_validacion(
    motor: AsyncEngine,
    almacen: AlmacenS3,
    video_ids: Sequence[uuid.UUID] | None = None,
    *,
    simular: bool = False,
) -> ResultadoLimpieza:
    """Sin `video_ids` (`None`), todos los videos de validación; con `video_ids`, solo esos (`[]` → nada). Lanza
    `LimpiezaRechazada`, `FalloS3` (primera pasada o, al simular, el recuento) o errores de la base (los de conexión,
    como `BaseNoDisponible`)."""
    if video_ids is not None and not video_ids:
        return ResultadoLimpieza(videos=0, objetos=0, simulada=simular)
    async with sesion.transaccion(motor) as conexion:
        if video_ids is not None:
            pedidos = list(dict.fromkeys(video_ids))
            filas = {
                fila.id: fila
                for fila in await conexion.execute(
                    select(Video.id, Video.nombre, Video.ref_cliente).where(Video.id.in_(pedidos))
                )
            }
            inexistentes = [str(i) for i in pedidos if i not in filas]
            sin_prefijo = [
                str(i)
                for i in pedidos
                if i in filas and not es_dato_de_validacion(filas[i].nombre, filas[i].ref_cliente)
            ]
            if inexistentes or sin_prefijo:
                raise LimpiezaRechazada(inexistentes, sin_prefijo)
            objetivo = pedidos
        else:
            objetivo = list((await conexion.execute(select(Video.id).where(*_es_de_validacion()))).scalars())
    if not objetivo:
        return ResultadoLimpieza(videos=0, objetos=0, simulada=simular)
    prefijos = _prefijos(objetivo)
    if simular:
        objetos = await anyio.to_thread.run_sync(_contar, almacen, prefijos)
        return ResultadoLimpieza(len(objetivo), objetos, [str(i) for i in objetivo], simulada=True)
    objetos = await anyio.to_thread.run_sync(_borrar, almacen, prefijos)
    async with sesion.transaccion(motor) as conexion:
        borrados = list(
            (
                await conexion.execute(
                    delete(Video).where(Video.id.in_(objetivo), *_es_de_validacion()).returning(Video.id)
                )
            ).scalars()
        )
    extra, restos, motivo = await anyio.to_thread.run_sync(_segunda_pasada, almacen, prefijos)
    return ResultadoLimpieza(
        videos=len(borrados),
        objetos=objetos + extra,
        video_ids=[str(i) for i in borrados],
        restos_s3=restos,
        motivo_restos=motivo,
    )
