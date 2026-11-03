"""Respuesta de `GET /v1/admin/stats` (ARCHITECTURE §5.5), BE-2.3.

- `UltimoVideo`: `{numero, creado_en}` del video más reciente que no está eliminado (`creado_en` en UTC con `Z` y sin
  fracciones, §5.1).
- `ResumenPanel`: los cuatro datos del panel; `ultimo_video` es `null` si no hay ningún video sin eliminar.

Las respuestas prohíben campos de más (como el resto de respuestas de §5.5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.esquemas.comun import FechaUtc


class UltimoVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: int
    creado_en: FechaUtc


class ResumenPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_fotos: int
    total_lugares: int
    alertas_activas: int
    ultimo_video: UltimoVideo | None
