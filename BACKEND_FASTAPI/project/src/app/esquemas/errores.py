"""Formato de error común (ARCHITECTURE §5.1) y detalle de `422 VALIDACION` (§5.6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CuerpoError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(description="Código fijo de §5.6, p. ej. `NO_ENCONTRADO`")
    mensaje: str = Field(min_length=1, description="Texto para humanos")
    detalle: dict[str, Any] | None = None


class ErrorRespuesta(BaseModel):
    """`{"error": {"codigo": …, "mensaje": …, "detalle": {…} | null}}`"""

    model_config = ConfigDict(extra="forbid")

    error: CuerpoError


class CampoInvalido(BaseModel):
    """Elemento de `detalle.campos` en `422 VALIDACION`."""

    model_config = ConfigDict(extra="forbid")

    campo: str
    motivo: str
