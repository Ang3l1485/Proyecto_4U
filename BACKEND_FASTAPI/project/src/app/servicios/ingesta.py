"""Ingesta del dataset (ARCHITECTURE §4.6, mensajes de §5.8): de un lote de mensajes de `ingesta` a fotos
`procesada` (con vector y miniatura) o en `error`.

`procesar_lote(deps, mensajes)` → `list[Decision]` (una por mensaje, en el mismo orden): `borrar = True` si todo lo
que nombra el mensaje terminó (procesado, descartado o con error permanente); `False` si algo falló de forma
transitoria (el mensaje vuelve a la cola tras la visibilidad, infra §5.6). No toca la cola: lo hace `app.worker`.

Pasos por foto (una «unidad»; dos mensajes del mismo lote que nombran la misma foto comparten unidad):
1. Transacción: `bloquear_video` (orden video → imágenes, §4.5) y la foto con `FOR UPDATE`. Video inexistente o
   `eliminado`, o foto inexistente → descartar. Evento de S3 con el mismo ETag que una foto ya `procesada` o en
   `error` → descartar (duplicado). Foto `pendiente_subida` y evento de S3 → pasa a `subida` (con `bytes` y `etag` del
   evento) y `recalcular_estado`. `reprocesar_imagen` entra aquí sin la regla del ETag.
2. Fuera de la base: `descargar` (≤ `REC_MAX_BYTES_FOTO`), `preparar` (dominio.imagenes) en un hilo y `escribir` la
   miniatura en `thumbs/{video_id}/{imagen_id}.jpg`.
3. `POST /v1/embed` en grupos de `WORKER_LOTE_EMBEDDING` copias reducidas, prioridad `baja`. Si la `version_vector`
   devuelta no es `EMBEDDING_VERSION_VECTOR`, no se guarda nada (`version_vector_distinta`, transitorio).
4. Transacción: `bloquear_video`, foto `FOR UPDATE`, vector (`INSERT … ON CONFLICT (imagen_id, version_vector) DO
   UPDATE`, con `creado_en = now()`), foto `procesada` (`error = NULL`, `bytes`, `etag` del objeto descargado,
   `ancho`, `alto`, `intentos + 1`) y `recalcular_estado`.

Error permanente (no es JPEG, demasiado grande, lado menor < `REC_LADO_MIN_PX`, embeddings la rechaza): en una
transacción con el mismo orden de bloqueo, la foto pasa a `error` con el motivo, se borran sus vectores (de todas las
versiones) e `intentos + 1`. Transitorio (S3, base, embeddings caído o lento, versión distinta, error imprevisto): no
se escribe nada más y el mensaje se conserva.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import anyio.to_thread
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clientes import embedding
from app.clientes.embedding import EmbeddingNoDisponible, ImagenRechazada, RespuestaNoValida, Vectores
from app.clientes.s3 import FalloS3, ObjetoDemasiadoGrande
from app.clientes.sqs import MensajeSqs
from app.config import Settings
from app.db import sesion
from app.db.modelos import Embedding, Imagen
from app.dominio import imagenes as dominio_imagenes
from app.dominio import mensajes
from app.dominio.enumerados import EstadoImagen, EstadoVideo
from app.dominio.recoleccion import clave_miniatura, ids_de_clave
from app.logs import obtener_logger, registrar
from app.servicios.recoleccion import bloquear_video, recalcular_estado

log = obtener_logger("app.worker")

ENTERO_MAX = 2_147_483_647  # `imagenes.bytes` es `integer`


class Resultado(StrEnum):
    procesada = "procesada"
    error = "error"  # error permanente: la foto quedó en `error`
    descartado = "descartado"
    transitorio = "transitorio"


#: Motivos de `mensaje_descartado` (§5.10).
VIDEO_NO_EXISTE = "video_no_existe"
VIDEO_ELIMINADO = "video_eliminado"
IMAGEN_NO_EXISTE = "imagen_no_existe"
CLAVE_NO_RECONOCIDA = "clave_no_reconocida"
DUPLICADO = "duplicado"
OBJETO_NO_EXISTE = "objeto_no_existe"


@dataclass
class Dependencias:
    """Lo que necesita la ingesta. `almacen` es un `AlmacenS3` (o un doble con `descargar` y `escribir`);
    `vectorizar(imagenes)` → `Vectores` (por defecto, `embedding.vectorizar` con prioridad `baja`)."""

    motor: AsyncEngine
    almacen: Any
    ajustes: Settings
    vectorizar: Callable[[Sequence[bytes]], Awaitable[Vectores]] | None = None

    def __post_init__(self) -> None:
        if self.vectorizar is None:
            ajustes = self.ajustes

            async def _vectorizar(imagenes: Sequence[bytes]) -> Vectores:
                return await embedding.vectorizar(ajustes, imagenes, prioridad="baja")

            self.vectorizar = _vectorizar


@dataclass
class Unidad:
    """Una foto a procesar. `origen` = `s3` (evento) o `reprocesar`."""

    imagen_id: uuid.UUID
    video_id: uuid.UUID | None
    origen: str
    etag_evento: str | None = None
    bytes_evento: int | None = None
    resultado: Resultado | None = None
    motivo: str | None = None
    s3_key: str | None = None
    datos_bytes: int | None = None
    etag: str | None = None
    preparada: dominio_imagenes.ImagenPreparada | None = None
    inicio: float = field(default_factory=time.monotonic)

    def terminar(self, resultado: Resultado, motivo: str | None = None) -> None:
        self.resultado, self.motivo = resultado, motivo

    @property
    def pendiente(self) -> bool:
        return self.resultado is None

    def campos(self) -> dict[str, Any]:
        return {"imagen_id": str(self.imagen_id), "video_id": str(self.video_id) if self.video_id else None}


@dataclass
class Decision:
    mensaje: MensajeSqs
    borrar: bool
    unidades: list[Unidad] = field(default_factory=list)


def _bytes_validos(n: int | None) -> int | None:
    return n if n is not None and 0 <= n <= ENTERO_MAX else None


def _descartar(unidad: Unidad, motivo: str) -> None:
    unidad.terminar(Resultado.descartado, motivo)
    registrar(log, "mensaje_descartado", motivo=motivo, origen=unidad.origen, **unidad.campos())


def _transitorio(unidad: Unidad, motivo: str, nivel: int = logging.WARNING, **extra: Any) -> None:
    unidad.terminar(Resultado.transitorio, motivo)
    registrar(log, "ingesta_transitoria", nivel, motivo=motivo, origen=unidad.origen, **unidad.campos(), **extra)


# --- 0. Mensajes → unidades --------------------------------------------------------------------------------------
def _unidades_de(mensaje: MensajeSqs, por_imagen: dict[uuid.UUID, Unidad]) -> list[Unidad] | None:
    """Las unidades que nombra el mensaje (compartidas si se repiten en el lote), o `None` si no hay nada que hacer
    (prueba de S3, mensaje no reconocido o solo claves que no son de fotos)."""
    contenido = mensajes.interpretar(mensaje.cuerpo)
    if isinstance(contenido, mensajes.PruebaS3):
        registrar(log, "mensaje_descartado", motivo="prueba_s3", mensaje_id=mensaje.id)
        return None
    if isinstance(contenido, mensajes.NoReconocido):
        registrar(log, "mensaje_no_reconocido", logging.WARNING, motivo=contenido.motivo, mensaje_id=mensaje.id)
        return None
    nuevas: list[tuple[uuid.UUID, Unidad]] = []
    if isinstance(contenido, mensajes.Reprocesar):
        nuevas.append((contenido.imagen_id, Unidad(contenido.imagen_id, None, "reprocesar")))
    else:
        for objeto in contenido.objetos:
            ids = ids_de_clave(objeto.clave)
            if ids is None:
                registrar(log, "mensaje_descartado", motivo=CLAVE_NO_RECONOCIDA, mensaje_id=mensaje.id)
                continue
            video_id, imagen_id = ids
            nuevas.append((imagen_id, Unidad(imagen_id, video_id, "s3", objeto.etag, objeto.bytes)))
    unidades: list[Unidad] = []
    for imagen_id, unidad in nuevas:
        existente = por_imagen.get(imagen_id)
        if existente is None:
            por_imagen[imagen_id] = unidad
            existente = unidad
        unidades.append(existente)
    return unidades


# --- 1. Preparar en la base --------------------------------------------------------------------------------------
async def _foto_bloqueada(conexion: AsyncConnection, unidad: Unidad) -> Any | None:
    """Bloquea el video y después la foto (orden de §4.5). `None` (y la unidad descartada) si no hay qué procesar."""
    if unidad.video_id is None:  # reprocesar: el video sale de la foto (lectura sin bloqueo; se bloquea después)
        video_id = (
            await conexion.execute(select(Imagen.video_id).where(Imagen.id == unidad.imagen_id))
        ).scalar_one_or_none()
        if video_id is None:
            _descartar(unidad, IMAGEN_NO_EXISTE)
            return None
        unidad.video_id = video_id
    estado_video = await bloquear_video(conexion, unidad.video_id)
    if estado_video is None:
        _descartar(unidad, VIDEO_NO_EXISTE)
        return None
    if estado_video == EstadoVideo.eliminado:
        _descartar(unidad, VIDEO_ELIMINADO)
        return None
    consulta = (
        select(Imagen.estado, Imagen.etag, Imagen.s3_key)
        .where(Imagen.id == unidad.imagen_id, Imagen.video_id == unidad.video_id)
        .with_for_update()
    )
    fila = (await conexion.execute(consulta)).first()
    if fila is None:
        _descartar(unidad, IMAGEN_NO_EXISTE)
    return fila


async def _preparar_en_base(motor: AsyncEngine, unidad: Unidad) -> None:
    async with sesion.transaccion(motor) as conexion:
        fila = await _foto_bloqueada(conexion, unidad)
        if fila is None:
            return
        unidad.s3_key = fila.s3_key
        if unidad.origen != "s3":
            return
        terminada = fila.estado in (EstadoImagen.procesada, EstadoImagen.error)
        if terminada and unidad.etag_evento and fila.etag == unidad.etag_evento:
            _descartar(unidad, DUPLICADO)
            return
        if fila.estado == EstadoImagen.pendiente_subida:
            valores: dict[str, Any] = {"estado": EstadoImagen.subida}
            if unidad.etag_evento:
                valores["etag"] = unidad.etag_evento
            if (n := _bytes_validos(unidad.bytes_evento)) is not None:
                valores["bytes"] = n
            await conexion.execute(update(Imagen).where(Imagen.id == unidad.imagen_id).values(**valores))
            await recalcular_estado(conexion, unidad.video_id)


# --- 2. S3 y Pillow ----------------------------------------------------------------------------------------------
async def _descargar_y_preparar(deps: Dependencias, unidad: Unidad) -> None:
    ajustes = deps.ajustes
    try:
        objeto = await anyio.to_thread.run_sync(deps.almacen.descargar, unidad.s3_key, ajustes.rec_max_bytes_foto)
    except ObjetoDemasiadoGrande as exc:
        unidad.datos_bytes = _bytes_validos(exc.bytes)
        unidad.terminar(
            Resultado.error, dominio_imagenes.motivo_demasiado_grande(exc.bytes, ajustes.rec_max_bytes_foto)
        )
        return
    except FalloS3 as exc:
        _transitorio(unidad, f"s3: {exc}")
        return
    if objeto is None:
        _descartar(unidad, OBJETO_NO_EXISTE)
        return
    unidad.datos_bytes, unidad.etag = len(objeto.datos), objeto.etag
    try:
        unidad.preparada = await anyio.to_thread.run_sync(
            lambda: dominio_imagenes.preparar(
                objeto.datos,
                max_bytes=ajustes.rec_max_bytes_foto,
                lado_min=ajustes.rec_lado_min_px,
                lado_miniatura=ajustes.miniatura_lado_px,
                calidad_miniatura=ajustes.miniatura_calidad,
                lado_embedding=ajustes.worker_lado_embedding_px,
            )
        )
    except dominio_imagenes.ImagenNoValida as exc:
        unidad.terminar(Resultado.error, exc.motivo)
        return
    try:
        clave = clave_miniatura(unidad.video_id, unidad.imagen_id)
        await anyio.to_thread.run_sync(deps.almacen.escribir, clave, unidad.preparada.miniatura)
    except FalloS3 as exc:
        _transitorio(unidad, f"s3: {exc}")


# --- 3. Embeddings ----------------------------------------------------------------------------------------------
async def _vectorizar(deps: Dependencias, unidades: list[Unidad]) -> dict[uuid.UUID, tuple[str, list[float]]]:
    """Vectores de las unidades listas, en grupos de `WORKER_LOTE_EMBEDDING`. Una imagen rechazada queda en `error`
    y su grupo se repite sin ella. Si embeddings no está o la versión no coincide, las que faltan son transitorias."""
    resultado: dict[uuid.UUID, tuple[str, list[float]]] = {}
    tamano = max(1, min(8, deps.ajustes.worker_lote_embedding))
    pendientes = list(unidades)
    while pendientes:
        grupo, pendientes = pendientes[:tamano], pendientes[tamano:]
        while grupo:
            try:
                respuesta = await deps.vectorizar([u.preparada.reducida for u in grupo])
            except ImagenRechazada as exc:
                rechazada = grupo.pop(exc.indice)
                rechazada.terminar(Resultado.error, f"embeddings la rechazó ({exc.codigo})")
                continue
            except EmbeddingNoDisponible as exc:
                for unidad in grupo + pendientes:
                    _transitorio(unidad, f"embedding: {exc}")
                return resultado
            except RespuestaNoValida as exc:
                for unidad in grupo + pendientes:
                    _transitorio(unidad, f"embedding: respuesta no válida ({exc})", logging.ERROR)
                return resultado
            if respuesta.version_vector != deps.ajustes.embedding_version_vector:
                registrar(
                    log,
                    "version_vector_distinta",
                    logging.ERROR,
                    esperada=deps.ajustes.embedding_version_vector,
                    recibida=respuesta.version_vector,
                )
                for unidad in grupo + pendientes:
                    _transitorio(unidad, "version_vector distinta de EMBEDDING_VERSION_VECTOR")
                return resultado
            for unidad, vector in zip(grupo, respuesta.vectores, strict=True):
                resultado[unidad.imagen_id] = (respuesta.version_vector, vector)
            grupo = []
    return resultado


# --- 4. Guardar ---------------------------------------------------------------------------------------------------
async def _guardar(motor: AsyncEngine, unidad: Unidad, version: str, vector: list[float]) -> None:
    preparada = unidad.preparada
    async with sesion.transaccion(motor) as conexion:
        if await _foto_bloqueada(conexion, unidad) is None:
            return
        insercion = insert(Embedding).values(imagen_id=unidad.imagen_id, version_vector=version, vector=vector)
        insercion = insercion.on_conflict_do_update(
            index_elements=[Embedding.imagen_id, Embedding.version_vector],
            set_={"vector": insercion.excluded.vector, "creado_en": func.now()},
        )
        await conexion.execute(insercion)
        valores: dict[str, Any] = {
            "estado": EstadoImagen.procesada,
            "error": None,
            "ancho": preparada.ancho,
            "alto": preparada.alto,
            "intentos": Imagen.intentos + 1,
            "bytes": _bytes_validos(unidad.datos_bytes),
        }
        if unidad.etag:
            valores["etag"] = unidad.etag
        await conexion.execute(update(Imagen).where(Imagen.id == unidad.imagen_id).values(**valores))
        await recalcular_estado(conexion, unidad.video_id)
    unidad.terminar(Resultado.procesada)
    registrar(
        log,
        "imagen_procesada",
        origen=unidad.origen,
        version_vector=version,
        ancho=preparada.ancho,
        alto=preparada.alto,
        bytes=unidad.datos_bytes,
        duracion_ms=round((time.monotonic() - unidad.inicio) * 1000),
        **unidad.campos(),
    )


async def _guardar_error(motor: AsyncEngine, unidad: Unidad) -> None:
    motivo = unidad.motivo or "error"
    async with sesion.transaccion(motor) as conexion:
        if await _foto_bloqueada(conexion, unidad) is None:
            return
        await conexion.execute(delete(Embedding).where(Embedding.imagen_id == unidad.imagen_id))
        valores: dict[str, Any] = {"estado": EstadoImagen.error, "error": motivo, "intentos": Imagen.intentos + 1}
        if (n := _bytes_validos(unidad.datos_bytes)) is not None:
            valores["bytes"] = n
        if unidad.etag:
            valores["etag"] = unidad.etag
        if unidad.preparada is not None:
            valores |= {"ancho": unidad.preparada.ancho, "alto": unidad.preparada.alto}
        await conexion.execute(update(Imagen).where(Imagen.id == unidad.imagen_id).values(**valores))
        await recalcular_estado(conexion, unidad.video_id)
    unidad.terminar(Resultado.error, motivo)
    registrar(log, "imagen_con_error", logging.WARNING, origen=unidad.origen, motivo=motivo, **unidad.campos())


# --- Lote ---------------------------------------------------------------------------------------------------------
async def _con_errores_controlados(unidad: Unidad, paso: Callable[[], Awaitable[None]]) -> None:
    """Ejecuta un paso de la unidad; la base caída o un error imprevisto la dejan transitoria (no tumban el lote)."""
    try:
        await paso()
    except sesion.BaseNoDisponible as exc:
        _transitorio(unidad, f"base: {exc}")
    except Exception as exc:
        _transitorio(unidad, f"imprevisto: {sesion.describir(exc)}", logging.ERROR, exc_info=True)


async def procesar_lote(deps: Dependencias, recibidos: Sequence[MensajeSqs]) -> list[Decision]:
    por_imagen: dict[uuid.UUID, Unidad] = {}
    decisiones = [Decision(m, borrar=True, unidades=_unidades_de(m, por_imagen) or []) for m in recibidos]
    unidades = list(por_imagen.values())

    for unidad in unidades:
        await _con_errores_controlados(unidad, lambda u=unidad: _preparar_en_base(deps.motor, u))
    for unidad in [u for u in unidades if u.pendiente]:
        await _con_errores_controlados(unidad, lambda u=unidad: _descargar_y_preparar(deps, u))

    listas = [u for u in unidades if u.pendiente]
    try:
        vectores = await _vectorizar(deps, listas)
    except Exception as exc:  # un doble de `vectorizar` que falla de otra forma
        vectores = {}
        for unidad in [u for u in listas if u.pendiente]:
            _transitorio(unidad, f"imprevisto: {sesion.describir(exc)}", logging.ERROR)
    for unidad in listas:
        if unidad.pendiente and unidad.imagen_id in vectores:
            version, vector = vectores[unidad.imagen_id]
            await _con_errores_controlados(unidad, lambda u=unidad, v=version, x=vector: _guardar(deps.motor, u, v, x))

    for unidad in [u for u in unidades if u.resultado == Resultado.error and u.motivo]:
        await _con_errores_controlados(unidad, lambda u=unidad: _guardar_error(deps.motor, u))
    for unidad in [u for u in unidades if u.pendiente]:  # no debería quedar ninguna
        _transitorio(unidad, "sin terminar")

    for decision in decisiones:
        decision.borrar = all(u.resultado != Resultado.transitorio for u in decision.unidades)
    return decisiones
