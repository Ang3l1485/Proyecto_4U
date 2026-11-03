"""Respuestas de `GET /v1/health` y `GET /v1/health/ready` (ARCHITECTURE §5.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SaludRespuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: Literal["ok"]
    version: str = Field(description="Versión del backend")
    commit: str = Field(description="SHA corto del commit desplegado")


class PreparacionRespuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: Literal["ok"]
    db: Literal["ok"] = Field(description="Si la base no responde, el endpoint responde `503 BASE_NO_DISPONIBLE`")
    embedding: Literal["ok", "no_disponible"]
