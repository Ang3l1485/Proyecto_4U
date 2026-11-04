"""Filas de `auditoria` (ARCHITECTURE §5.7). BE-1.3 las escribe para `usuario.*`; cada lote añade sus acciones.

`anotar` va dentro de la transacción del cambio que registra (`sesion.transaccion`): si el cambio se deshace, la fila
de auditoría también. `detalle` es un objeto JSON sin secretos: nunca contraseñas, hashes, tokens ni URLs firmadas.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.modelos import Auditoria


async def anotar(
    conexion: AsyncConnection,
    *,
    accion: str,
    entidad: str,
    entidad_id: uuid.UUID | str | None = None,
    actor_id: uuid.UUID | None = None,
    detalle: Mapping[str, Any] | None = None,
) -> None:
    """Inserta una fila (`creado_en` lo pone la base)."""
    await conexion.execute(
        insert(Auditoria).values(
            accion=accion,
            entidad=entidad,
            entidad_id=str(entidad_id) if entidad_id is not None else None,
            actor_id=actor_id,
            detalle=dict(detalle or {}),
        )
    )
