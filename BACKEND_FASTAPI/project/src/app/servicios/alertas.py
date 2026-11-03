"""Alertas (ARCHITECTURE §4.11, §5.3 `GET /v1/alerts`, §5.5 `/v1/admin/alerts`, ADR-BE-10), BE-3.3.

- `foto(motor, *, desde=None, dias_tombstone)` → `AlertasRespuesta`: sin `desde` (o con uno que no sirve para
  diferencias, `dominio.alertas.pide_foto_completa`), las activas sin borrar; con `desde`, las filas con `actualizado_en
  ≥ desde − MARGEN_DESDE_S`: las vivas en `alertas` (activas o no) y las borradas (*tombstones*) en `eliminadas`. Orden
  `actualizado_en`, `id`. `generado_en` = `now()` de la transacción de lectura (el reloj de la base, el mismo de
  `actualizado_en`).
- `listar_admin(motor, *, q=None, tipo=None, prioridad=None, activa=None)` → `list[AlertaAdmin]`: sin borradas, de la
  modificada más recientemente a la más antigua (a igualdad, `id`); `q` con `dominio.alertas.coincide`.
- `guardar(motor, *, usuario_id, alerta_id, datos, version_esperada=None, origen="put")` → `Guardado`: crea, reemplaza
  o restaura (un *tombstone* con el mismo id vuelve a existir) con `version + 1`; sin cambios no escribe.
  `version_esperada` (el `If-Match`) distinta de la versión guardada, o una alerta que no existe →
  `ConflictoVersion`.
- `borrar(motor, *, usuario_id, alerta_id, origen="delete")` → `Borrado(existia)`: fija `eliminada_en` y
  `actualizado_en` (*tombstone*) y sube `version`; un id desconocido o ya borrado no cambia nada.
- `sincronizar(motor, *, usuario_id, cambios)` → `SincronizarRespuesta`: cada cambio en su propia transacción, en
  orden; uno no válido da `estado = error` (`VALIDACION`) sin tocar los demás.
- `purgar_tombstones(motor, dias)` → filas borradas; `limpieza_diaria(motor, dias, …)` la repite cada 24 h en `api`.

Cada cambio deja su fila de `auditoria` (`alerta.upsert`, `alerta.eliminar`, §5.7) en la misma transacción y, tras
confirmar, su evento (`alerta_guardada`, `alerta_eliminada`, §5.10; sin el mensaje).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import aliased

from app.db import sesion
from app.db.modelos import Alerta as FilaAlerta
from app.db.modelos import Usuario
from app.dominio.alertas import CAMPOS, campos_cambiados, coincide, corte_desde, pide_foto_completa
from app.dominio.enumerados import PrioridadAlerta, TipoAlerta
from app.esquemas.alertas import (
    CODIGO_VALIDACION,
    ESTADO_ERROR,
    ESTADO_OK,
    Alerta,
    AlertaAdmin,
    AlertaEntrada,
    AlertasRespuesta,
    Cambio,
    ResultadoCambio,
    SincronizarRespuesta,
)
from app.esquemas.comun import Referencia
from app.logs import obtener_logger, registrar
from app.servicios import auditoria

log = obtener_logger(__name__)

_COLUMNAS = tuple(FilaAlerta.__table__.c)
#: Primera purga de *tombstones* tras arrancar `api` y pausa entre purgas (la «limpieza diaria» de §5.10).
ESPERA_LIMPIEZA_S = 60.0
INTERVALO_LIMPIEZA_S = 24 * 3600.0
TAREA_LIMPIEZA = "tombstones_alertas"


class ConflictoVersion(Exception):
    """`If-Match` no coincide con la versión guardada (`actual`; `None` si la alerta no existe)."""

    def __init__(self, actual: int | None) -> None:
        self.actual = actual
        super().__init__(f"versión actual: {actual}")


@dataclass(frozen=True)
class Guardado:
    alerta: AlertaAdmin
    #: `crear`, `editar`, `restaurar` o `None` (sin cambios: nada escrito).
    operacion: str | None

    @property
    def creada(self) -> bool:
        """¿Responde `201`? Al crear y al restaurar una borrada (antes no existía para la app)."""
        return self.operacion in ("crear", "restaurar")


@dataclass(frozen=True)
class Borrado:
    existia: bool


# --- Conversión ---------------------------------------------------------------------------------------------------
def _publica(fila: Any) -> Alerta:
    return Alerta(
        id=fila.id,
        lat=fila.lat,
        lng=fila.lng,
        mensaje=fila.mensaje,
        tipo=fila.tipo,
        prioridad=fila.prioridad,
        radio_m=fila.radio_m,
        activa=fila.activa,
        vigencia_desde=fila.vigencia_desde,
        vigencia_hasta=fila.vigencia_hasta,
        actualizado_en=fila.actualizado_en,
        version=fila.version,
    )


def _admin(fila: Any) -> AlertaAdmin:
    return AlertaAdmin(
        **_publica(fila).model_dump(),
        creado_en=fila.creado_en,
        creado_por=Referencia(id=fila.creado_por, nombre=fila.creado_por_nombre),
        actualizado_por=Referencia(id=fila.actualizado_por, nombre=fila.actualizado_por_nombre),
    )


def consulta_admin() -> Select:
    """Las columnas de `alertas` más los nombres de quien la creó y de quien la cambió por última vez."""
    creador = aliased(Usuario)
    editor = aliased(Usuario)
    return (
        select(
            *_COLUMNAS,
            creador.nombre.label("creado_por_nombre"),
            editor.nombre.label("actualizado_por_nombre"),
        )
        .select_from(FilaAlerta)
        .join(creador, creador.id == FilaAlerta.creado_por)
        .join(editor, editor.id == FilaAlerta.actualizado_por)
    )


# --- Lectura ------------------------------------------------------------------------------------------------------
async def foto(motor: AsyncEngine, *, desde: datetime | None = None, dias_tombstone: int) -> AlertasRespuesta:
    orden = (FilaAlerta.actualizado_en, FilaAlerta.id)
    async with sesion.transaccion(motor) as conexion:
        ahora = (await conexion.execute(select(func.now()))).scalar_one()
        if pide_foto_completa(desde, ahora, dias_tombstone):
            consulta = select(*_COLUMNAS).where(FilaAlerta.activa.is_(True), FilaAlerta.eliminada_en.is_(None))
            filas = (await conexion.execute(consulta.order_by(*orden))).all()
            return AlertasRespuesta(
                generado_en=ahora, completo=True, alertas=[_publica(f) for f in filas], eliminadas=[]
            )
        assert desde is not None  # noqa: S101 (pide_foto_completa da True sin desde)
        consulta = select(*_COLUMNAS).where(FilaAlerta.actualizado_en >= corte_desde(desde))
        filas = (await conexion.execute(consulta.order_by(*orden))).all()
    return AlertasRespuesta(
        generado_en=ahora,
        completo=False,
        alertas=[_publica(f) for f in filas if f.eliminada_en is None],
        eliminadas=[f.id for f in filas if f.eliminada_en is not None],
    )


async def listar_admin(
    motor: AsyncEngine,
    *,
    q: str | None = None,
    tipo: TipoAlerta | None = None,
    prioridad: PrioridadAlerta | None = None,
    activa: bool | None = None,
) -> list[AlertaAdmin]:
    consulta = consulta_admin().where(FilaAlerta.eliminada_en.is_(None))
    if tipo is not None:
        consulta = consulta.where(FilaAlerta.tipo == tipo)
    if prioridad is not None:
        consulta = consulta.where(FilaAlerta.prioridad == prioridad)
    if activa is not None:
        consulta = consulta.where(FilaAlerta.activa.is_(activa))
    consulta = consulta.order_by(FilaAlerta.actualizado_en.desc(), FilaAlerta.id)
    async with sesion.transaccion(motor) as conexion:
        filas = (await conexion.execute(consulta)).all()
    return [_admin(f) for f in filas if coincide(f.mensaje, q)]


# --- Escritura ----------------------------------------------------------------------------------------------------
async def _bloquear(conexion: AsyncConnection, alerta_id: uuid.UUID) -> Any:
    consulta = select(*_COLUMNAS).where(FilaAlerta.id == alerta_id).with_for_update()
    return (await conexion.execute(consulta)).first()


async def _crear(conexion: AsyncConnection, alerta_id: uuid.UUID, valores: dict[str, Any], usuario_id: uuid.UUID):
    """`INSERT … ON CONFLICT (id) DO NOTHING`: `None` si otra petición la creó a la vez (esperó a que confirmara)."""
    insercion = (
        pg_insert(FilaAlerta)
        .values(id=alerta_id, **valores, creado_por=usuario_id, actualizado_por=usuario_id)
        .on_conflict_do_nothing(index_elements=[FilaAlerta.id])
        .returning(FilaAlerta.id)
    )
    return (await conexion.execute(insercion)).first()


async def guardar(
    motor: AsyncEngine,
    *,
    usuario_id: uuid.UUID,
    alerta_id: uuid.UUID,
    datos: AlertaEntrada,
    version_esperada: int | None = None,
    origen: str = "put",
) -> Guardado:
    valores = datos.valores()
    async with sesion.transaccion(motor) as conexion:
        actual = await _bloquear(conexion, alerta_id)
        operacion: str | None
        if actual is None and version_esperada is not None:
            raise ConflictoVersion(None)
        if actual is None and await _crear(conexion, alerta_id, valores, usuario_id) is not None:
            operacion, cambios, version = "crear", list(CAMPOS), 1
        else:
            if actual is None:  # la creó otra petición a la vez: ahora existe y se reemplaza
                actual = await _bloquear(conexion, alerta_id)
            if version_esperada is not None and actual.version != version_esperada:
                raise ConflictoVersion(actual.version)
            cambios = campos_cambiados(actual, valores)
            if actual.eliminada_en is not None:
                operacion = "restaurar"
            else:
                operacion = "editar" if cambios else None
            version = actual.version + 1 if operacion else actual.version
            if operacion:
                await conexion.execute(
                    update(FilaAlerta)
                    .where(FilaAlerta.id == alerta_id)
                    .values(
                        **valores,
                        version=version,
                        actualizado_en=func.now(),
                        actualizado_por=usuario_id,
                        eliminada_en=None,
                    )
                )
        if operacion:
            detalle: dict[str, Any] = {"operacion": operacion, "version": version, "cambios": cambios, "origen": origen}
            if operacion != "editar":
                detalle["mensaje"] = valores["mensaje"]
            await auditoria.anotar(
                conexion,
                accion="alerta.upsert",
                entidad="alerta",
                entidad_id=alerta_id,
                actor_id=usuario_id,
                detalle=detalle,
            )
        fila = (await conexion.execute(consulta_admin().where(FilaAlerta.id == alerta_id))).one()
    if operacion:
        registrar(
            log,
            "alerta_guardada",
            logging.INFO,
            operacion=operacion,
            alerta_id=str(alerta_id),
            version=version,
            cambios=cambios,
            origen=origen,
        )
    return Guardado(alerta=_admin(fila), operacion=operacion)


async def borrar(motor: AsyncEngine, *, usuario_id: uuid.UUID, alerta_id: uuid.UUID, origen: str = "delete") -> Borrado:
    cambio = (
        update(FilaAlerta)
        .where(FilaAlerta.id == alerta_id, FilaAlerta.eliminada_en.is_(None))
        .values(
            eliminada_en=func.now(),
            actualizado_en=func.now(),
            actualizado_por=usuario_id,
            version=FilaAlerta.version + 1,
        )
        .returning(FilaAlerta.version, FilaAlerta.mensaje)
    )
    async with sesion.transaccion(motor) as conexion:
        fila = (await conexion.execute(cambio)).first()
        if fila is not None:
            await auditoria.anotar(
                conexion,
                accion="alerta.eliminar",
                entidad="alerta",
                entidad_id=alerta_id,
                actor_id=usuario_id,
                detalle={"version": fila.version, "mensaje": fila.mensaje, "origen": origen},
            )
    registrar(
        log,
        "alerta_eliminada",
        logging.INFO,
        alerta_id=str(alerta_id),
        existia=fila is not None,
        version=fila.version if fila is not None else None,
        origen=origen,
    )
    return Borrado(existia=fila is not None)


async def sincronizar(motor: AsyncEngine, *, usuario_id: uuid.UUID, cambios: Sequence[Cambio]) -> SincronizarRespuesta:
    """Aplica cada cambio en su propia transacción y en el orden recibido. Un `upsert` cuya `alerta` no cumple
    `AlertaEntrada` da `estado = error` con `codigo = VALIDACION` y no se aplica; los demás siguen. Si la base falla a
    mitad, sale `BaseNoDisponible` (→ 503): lo ya aplicado queda y repetir la petición entera es seguro."""
    resultados: list[ResultadoCambio] = []
    for cambio in cambios:
        alerta_id = cambio.alerta_id
        if cambio.op == "upsert":
            assert cambio.alerta is not None  # noqa: S101 (lo garantiza Cambio)
            try:
                datos = AlertaEntrada.model_validate(cambio.alerta.entrada())
            except ValidationError:
                resultados.append(
                    ResultadoCambio(id=alerta_id, op="upsert", estado=ESTADO_ERROR, codigo=CODIGO_VALIDACION)
                )
                continue
            await guardar(motor, usuario_id=usuario_id, alerta_id=alerta_id, datos=datos, origen="sincronizar")
        else:
            await borrar(motor, usuario_id=usuario_id, alerta_id=alerta_id, origen="sincronizar")
        resultados.append(ResultadoCambio(id=alerta_id, op=cambio.op, estado=ESTADO_OK, codigo=None))
    async with sesion.transaccion(motor) as conexion:
        generado_en = (await conexion.execute(select(func.now()))).scalar_one()
    errores = sum(1 for r in resultados if r.estado == ESTADO_ERROR)
    registrar(
        log,
        "alertas_sincronizadas",
        logging.INFO,
        cambios=len(resultados),
        ok=len(resultados) - errores,
        errores=errores,
    )
    return SincronizarRespuesta(generado_en=generado_en, resultados=resultados)


# --- Purga de tombstones ------------------------------------------------------------------------------------------
async def purgar_tombstones(motor: AsyncEngine, dias: int) -> int:
    """Borra de verdad las alertas borradas hace más de `dias` días (`eliminada_en < now() − dias`). Devuelve
    cuántas."""
    purga = delete(FilaAlerta).where(FilaAlerta.eliminada_en < func.now() - func.make_interval(0, 0, 0, dias))
    async with sesion.transaccion(motor) as conexion:
        borradas = (await conexion.execute(purga)).rowcount or 0
    return borradas


async def limpieza_diaria(
    motor: AsyncEngine,
    dias: int,
    *,
    espera_inicial_s: float = ESPERA_LIMPIEZA_S,
    intervalo_s: float = INTERVALO_LIMPIEZA_S,
    dormir: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    purgar: Callable[[AsyncEngine, int], Awaitable[int]] | None = None,
) -> None:
    """Bucle de `api` (lo lanza y lo cancela el ciclo de vida de `main.py`): espera `espera_inicial_s` y después purga
    los *tombstones* cada `intervalo_s`. Un fallo se registra (`limpieza_fallida`) y el bucle sigue."""
    purgar = purgar or purgar_tombstones
    await dormir(espera_inicial_s)
    while True:
        inicio = time.perf_counter()
        try:
            borradas = await purgar(motor, dias)
        except sesion.BaseNoDisponible as exc:
            registrar(log, "limpieza_fallida", logging.WARNING, tarea=TAREA_LIMPIEZA, motivo=str(exc))
        except Exception as exc:
            registrar(
                log,
                "limpieza_fallida",
                logging.ERROR,
                tarea=TAREA_LIMPIEZA,
                motivo=sesion.describir(exc),
                exc_info=True,
            )
        else:
            registrar(
                log,
                "alertas_purgadas",
                logging.INFO,
                borradas=borradas,
                dias=dias,
                duracion_ms=int((time.perf_counter() - inicio) * 1000),
            )
        await dormir(intervalo_s)
