"""Purga de lo borrado (BE-4.1, ARCHITECTURE §4.12, ADR-BE-07 y ADR-BE-20).

**`worker`** (`procesar_purga(deps, mensajes)` → `list[DecisionPurga]`, mensajes de la cola `purga`, §5.8):
- `purgar_video`: con el video `eliminado`, borra los objetos de `dataset/{id}/` y `thumbs/{id}/` (primera pasada),
  las filas de `imagenes` (y en cascada `embeddings`), otra pasada por S3 (una miniatura que el `worker` escribiera
  entretanto) y fija `purgado_en`. Si el video no existe (lo borró `limpiar-validacion`) solo pasa por S3; si existe
  y **no** está `eliminado` (un `DELETE` que no llegó a confirmarse), descarta el mensaje sin tocar nada.
  Repetirlo no hace daño (con `purgado_en` ya puesto vuelve a pasar por S3 y no cambia la fila).
- `purgar_imagen`: bloquea el video del mensaje (así espera a que confirme la transacción de `api` que lo envió) y,
  si la fila de la imagen ya no existe, borra sus objetos (`s3_keys`, solo las dos claves de esa imagen); si existe,
  la transacción de `api` se deshizo después de enviar: descarta.
- Un mensaje que no encaja → se borra (`mensaje_no_reconocido`, `cola = purga`). S3, base o un error imprevisto →
  transitorio: el mensaje se queda (vuelve tras la visibilidad de `purga`, 300 s; a la sexta recepción, DLQ).

**`api`** (`reconciliador`, tarea del ciclo de vida de `main.py`): cada `RECONCILIADOR_CADA_MIN` reenvía
`purgar_video` de los videos `eliminado` hace más de `RECONCILIADOR_CADA_MIN` minutos sin `purgado_en`
(`reencolar_pendientes`). Cubre un envío que falló tras el `COMMIT` del `DELETE` y los mensajes que acabaron en la
DLQ o caducaron (4 días).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import anyio.to_thread
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clientes.s3 import AlmacenS3, FalloS3
from app.clientes.sqs import ColaSqs, FalloSqs, MensajeSqs
from app.db import sesion
from app.db.modelos import Imagen, Video
from app.dominio.enumerados import EstadoVideo
from app.dominio.mensajes import NoReconocido, PurgarImagen, PurgarVideo, cuerpo_purgar_video, interpretar_purga
from app.dominio.recoleccion import prefijos_del_video
from app.logs import obtener_logger, registrar

log = obtener_logger("app.worker")
log_api = obtener_logger(__name__)

#: Primera pasada del reconciliador tras arrancar `api` (después, cada `RECONCILIADOR_CADA_MIN`).
ESPERA_RECONCILIADOR_S = 60.0
#: Videos que reenvía como mucho en cada pasada (los más antiguos primero).
LIMITE_RECONCILIADOR = 100
#: Motivos de `purga_descartada`.
VIDEO_NO_ELIMINADO = "video_no_eliminado"
IMAGEN_EXISTE = "imagen_existe"


@dataclass(frozen=True)
class DependenciasPurga:
    motor: AsyncEngine
    almacen: AlmacenS3


@dataclass
class DecisionPurga:
    mensaje: MensajeSqs
    borrar: bool


async def _borrar_prefijos(almacen: AlmacenS3, prefijos: Sequence[str]) -> int:
    return await anyio.to_thread.run_sync(lambda: sum(almacen.borrar_prefijo(p) for p in prefijos))


async def purgar_video(deps: DependenciasPurga, video_id: uuid.UUID) -> None:
    inicio = time.perf_counter()
    async with sesion.transaccion(deps.motor) as conexion:
        consulta = select(Video.estado, Video.purgado_en).where(Video.id == video_id).with_for_update()
        fila = (await conexion.execute(consulta)).first()
    if fila is not None and fila.estado != EstadoVideo.eliminado:
        registrar(log, "purga_descartada", motivo=VIDEO_NO_ELIMINADO, tipo="purgar_video", video_id=str(video_id))
        return
    prefijos = prefijos_del_video(video_id)
    objetos = await _borrar_prefijos(deps.almacen, prefijos)
    imagenes = 0
    if fila is not None:
        from app.servicios import recoleccion

        async with sesion.transaccion(deps.motor) as conexion:
            await recoleccion.bloquear_video(conexion, video_id)
            imagenes = (await conexion.execute(delete(Imagen).where(Imagen.video_id == video_id))).rowcount or 0
    objetos += await _borrar_prefijos(deps.almacen, prefijos)
    if fila is not None and fila.purgado_en is None:
        async with sesion.transaccion(deps.motor) as conexion:
            await conexion.execute(
                update(Video)
                .where(Video.id == video_id, Video.purgado_en.is_(None))
                .values(purgado_en=func.now(), actualizado_en=func.now())
            )
    registrar(
        log,
        "video_purgado",
        video_id=str(video_id),
        objetos=objetos,
        imagenes=imagenes,
        existia=fila is not None,
        ya_purgado=fila is not None and fila.purgado_en is not None,
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
    )


async def purgar_imagen(deps: DependenciasPurga, mensaje: PurgarImagen) -> None:
    from app.servicios import recoleccion

    async with sesion.transaccion(deps.motor) as conexion:
        await recoleccion.bloquear_video(conexion, mensaje.video_id)  # espera a que confirme el DELETE de `api`
        existe = (await conexion.execute(select(Imagen.id).where(Imagen.id == mensaje.imagen_id))).scalar_one_or_none()
    if existe is not None:
        registrar(
            log,
            "purga_descartada",
            motivo=IMAGEN_EXISTE,
            tipo="purgar_imagen",
            imagen_id=str(mensaje.imagen_id),
            video_id=str(mensaje.video_id),
        )
        return
    # Cada clave como prefijo exacto: el rol del `worker` lista con `s3:prefix` `dataset/*` o `thumbs/*` (infra §5.8).
    objetos = await _borrar_prefijos(deps.almacen, mensaje.s3_keys)
    registrar(log, "imagen_purgada", imagen_id=str(mensaje.imagen_id), video_id=str(mensaje.video_id), objetos=objetos)


async def procesar_purga(deps: DependenciasPurga, mensajes: Sequence[MensajeSqs]) -> list[DecisionPurga]:
    """Un mensaje detrás de otro (como mucho `WORKER_MAX_MENSAJES`). Ver el docstring del módulo."""
    decisiones = []
    for mensaje in mensajes:
        orden = interpretar_purga(mensaje.cuerpo)
        if isinstance(orden, NoReconocido):
            registrar(
                log, "mensaje_no_reconocido", logging.WARNING, cola="purga", motivo=orden.motivo, mensaje_id=mensaje.id
            )
            decisiones.append(DecisionPurga(mensaje, borrar=True))
            continue
        ids = {"video_id": str(orden.video_id)}
        if isinstance(orden, PurgarImagen):
            ids["imagen_id"] = str(orden.imagen_id)
        try:
            if isinstance(orden, PurgarVideo):
                await purgar_video(deps, orden.video_id)
            else:
                await purgar_imagen(deps, orden)
        except (FalloS3, sesion.BaseNoDisponible) as exc:
            origen = "s3" if isinstance(exc, FalloS3) else "base"
            registrar(log, "purga_transitoria", logging.WARNING, motivo=f"{origen}: {exc}", **ids)
            decisiones.append(DecisionPurga(mensaje, borrar=False))
        except Exception as exc:
            registrar(
                log,
                "purga_transitoria",
                logging.ERROR,
                motivo=f"imprevisto: {sesion.describir(exc)}",
                exc_info=True,
                **ids,
            )
            decisiones.append(DecisionPurga(mensaje, borrar=False))
        else:
            decisiones.append(DecisionPurga(mensaje, borrar=True))
    return decisiones


# --- Reconciliador (api) ------------------------------------------------------------------------------------------
def sql_pendientes(minutos: int) -> Any:
    """Videos `eliminado` hace más de `minutos` sin `purgado_en`, los más antiguos primero."""
    return (
        select(Video.id, Video.eliminado_por)
        .where(
            Video.estado == EstadoVideo.eliminado,
            Video.purgado_en.is_(None),
            Video.eliminado_en < func.now() - func.make_interval(0, 0, 0, 0, 0, minutos),
        )
        .order_by(Video.eliminado_en, Video.id)
        .limit(LIMITE_RECONCILIADOR)
    )


@dataclass(frozen=True)
class Reencolado:
    pendientes: int
    enviados: int


async def reencolar_pendientes(motor: AsyncEngine, cola: ColaSqs, minutos: int) -> Reencolado:
    from app.servicios.videos import enviar

    async with sesion.transaccion(motor) as conexion:
        filas = (await conexion.execute(sql_pendientes(minutos))).all()
    enviados = 0
    for fila in filas:
        try:
            await enviar(cola, cuerpo_purgar_video(fila.id, fila.eliminado_por))
            enviados += 1
        except FalloSqs as exc:
            registrar(log_api, "purga_no_encolada", logging.WARNING, video_id=str(fila.id), motivo=str(exc))
    return Reencolado(pendientes=len(filas), enviados=enviados)


async def reconciliador(
    motor: AsyncEngine,
    cola: ColaSqs,
    minutos: int,
    *,
    espera_inicial_s: float = ESPERA_RECONCILIADOR_S,
    intervalo_s: float | None = None,
    dormir: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    accion: Callable[[AsyncEngine, ColaSqs, int], Awaitable[Reencolado]] | None = None,
) -> None:
    """Bucle de `api` (lo lanza y lo cancela el ciclo de vida de `main.py`, como la purga de alertas de BE-3.3):
    espera `espera_inicial_s` y después, cada `intervalo_s` (por defecto `minutos` · 60), `reencolar_pendientes`.
    Registra `purgas_reencoladas` (`INFO` si había pendientes; `DEBUG` si no) o `reconciliador_fallido` y sigue."""
    accion = accion or reencolar_pendientes
    intervalo = intervalo_s if intervalo_s is not None else minutos * 60.0
    await dormir(espera_inicial_s)
    while True:
        inicio = time.perf_counter()
        try:
            hecho = await accion(motor, cola, minutos)
        except sesion.BaseNoDisponible as exc:
            registrar(log_api, "reconciliador_fallido", logging.WARNING, motivo=str(exc))
        except Exception as exc:
            registrar(log_api, "reconciliador_fallido", logging.ERROR, motivo=sesion.describir(exc), exc_info=True)
        else:
            registrar(
                log_api,
                "purgas_reencoladas",
                logging.INFO if hecho.pendientes else logging.DEBUG,
                pendientes=hecho.pendientes,
                enviados=hecho.enviados,
                minutos=minutos,
                duracion_ms=int((time.perf_counter() - inicio) * 1000),
            )
        await dormir(intervalo)
