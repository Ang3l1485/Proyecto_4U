"""Resumen del panel (ARCHITECTURE §4.7, §5.5): `GET /v1/admin/stats`, BE-2.3.

- `resumen(motor)` → `ResumenPanel`, con **una** sentencia en una transacción corta (`sql_resumen()`): las cifras salen
  de la misma instantánea de la base.
- `total_fotos`: imágenes `procesada` de videos que no están `eliminado`.
- `total_lugares`: todas las filas de `lugares` (no tienen borrado lógico).
- `alertas_activas`: filas de `alertas` con `activa` y sin `eliminada_en`, sin mirar la vigencia (0 mientras no exista
  BE-3.3, que es quien escribe en `alertas`).
- `ultimo_video`: el video no eliminado más reciente por `creado_en` y, a igualdad, por `numero` (el primero de
  `GET /v1/admin/videos` con su orden por defecto); `None` si no hay ninguno.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import sesion
from app.db.modelos import Alerta, Imagen, Lugar, Video
from app.dominio.enumerados import EstadoImagen, EstadoVideo
from app.esquemas.estadisticas import ResumenPanel, UltimoVideo


def _ultimo(columna):
    """Columna `columna` del video no eliminado más reciente (subconsulta escalar; nula si no hay ninguno)."""
    return (
        select(columna)
        .where(Video.estado != EstadoVideo.eliminado)
        .order_by(Video.creado_en.desc(), Video.numero.desc())
        .limit(1)
        .scalar_subquery()
    )


def sql_resumen() -> Select:
    """La sentencia del resumen: una fila con `total_fotos`, `total_lugares`, `alertas_activas`, `ultimo_numero` y
    `ultimo_creado_en` (estas dos, nulas sin videos). Todo son subconsultas escalares de un solo `SELECT`."""
    fotos = (
        select(func.count())
        .select_from(Imagen)
        .join(Video, Video.id == Imagen.video_id)
        .where(Imagen.estado == EstadoImagen.procesada, Video.estado != EstadoVideo.eliminado)
        .scalar_subquery()
    )
    lugares = select(func.count()).select_from(Lugar).scalar_subquery()
    alertas = (
        select(func.count())
        .select_from(Alerta)
        .where(Alerta.activa.is_(True), Alerta.eliminada_en.is_(None))
        .scalar_subquery()
    )
    return select(
        fotos.label("total_fotos"),
        lugares.label("total_lugares"),
        alertas.label("alertas_activas"),
        _ultimo(Video.numero).label("ultimo_numero"),
        _ultimo(Video.creado_en).label("ultimo_creado_en"),
    )


async def resumen(motor: AsyncEngine) -> ResumenPanel:
    """Los totales del panel (arriba). Un fallo de conexión sale como `BaseNoDisponible` (→ 503, §4.4)."""
    async with sesion.transaccion(motor) as conexion:
        fila = (await conexion.execute(sql_resumen())).one()
    ultimo = None
    if fila.ultimo_numero is not None:
        ultimo = UltimoVideo(numero=fila.ultimo_numero, creado_en=fila.ultimo_creado_en)
    return ResumenPanel(
        total_fotos=fila.total_fotos,
        total_lugares=fila.total_lugares,
        alertas_activas=fila.alertas_activas,
        ultimo_video=ultimo,
    )
