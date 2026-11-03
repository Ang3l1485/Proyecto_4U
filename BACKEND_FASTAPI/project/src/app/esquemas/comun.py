"""Tipos comunes de los esquemas de la API (ARCHITECTURE §5.1), desde BE-2.1.

- `FechaUtc`: fecha de **salida**; se serializa en UTC con `Z` y sin fracciones (`2026-10-23T15:04:05Z`).
- `FechaConZona`: fecha de **entrada**; ISO-8601 con zona (`Z` o `±hh:mm`), devuelta en UTC. Sin zona, o fuera del
  rango de años 1–9999 al pasarla a UTC (p. ej. `0001-01-01T00:00:00+05:00`), → `422 VALIDACION` (sin la conversión,
  asyncpg lanzaba `OverflowError` al guardarla y la API respondía `500`).
- `Referencia`: `{id, nombre}` (p. ej. `creado_por`, `lugar`).
- `Pagina[T]`: `{items, total, pagina, por_pagina}` (§5.1, «Paginación»).
- `texto_admitido(valor)`: la regla de §4.4 para todo texto que llega a la base (`ValueError` → 422).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, PlainSerializer

from app.dominio.validaciones import motivo_texto_no_admitido


def _fecha_utc(valor: datetime) -> str:
    return valor.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _a_utc(valor: datetime) -> datetime:
    try:
        return valor.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError("Fecha fuera de rango (años 1–9999 en UTC).") from None


FechaUtc = Annotated[datetime, PlainSerializer(_fecha_utc, return_type=str, when_used="always")]
FechaConZona = Annotated[AwareDatetime, AfterValidator(_a_utc)]


class Referencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    nombre: str


class Pagina[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int
    pagina: int
    por_pagina: int


def texto_admitido(valor: str) -> str:
    """Devuelve `valor` o lanza `ValueError` con el motivo (carácter NUL o sustituto suelto, §4.4)."""
    motivo = motivo_texto_no_admitido(valor)
    if motivo is not None:
        raise ValueError(motivo)
    return valor
