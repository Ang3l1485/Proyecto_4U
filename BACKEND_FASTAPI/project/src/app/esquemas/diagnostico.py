"""Respuesta de `POST /v1/admin/diagnostico/vecinos` (ARCHITECTURE §5.5), BE-2.4.

La petición es `multipart/form-data` (una parte `foto`) y `?k=`: no tiene modelo Pydantic; la validan el router y
`app.dominio.fotos`. Las respuestas prohíben campos de más, como las demás de la API.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

#: Rango de `k` (§5.5) y su valor por defecto.
K_MIN = 1
K_MAX = 50
K_POR_DEFECTO = 5
#: Cifras decimales de `similitud` en la respuesta (el orden lo da la distancia sin redondear).
DECIMALES_SIMILITUD = 6


class VecinoDiagnostico(BaseModel):
    """Una imagen del índice: su coordenada, su rumbo (`real_legible`, o `null`), su lugar (o `null`) y la similitud
    coseno con la foto de consulta."""

    model_config = ConfigDict(extra="forbid")

    imagen_id: uuid.UUID
    video_id: uuid.UUID
    lat: float
    lng: float
    rumbo: float | None
    lugar_id: uuid.UUID | None
    similitud: float


class VecinosRespuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_vector: str
    k: int
    vecinos: list[VecinoDiagnostico]
    latencia_ms: int
