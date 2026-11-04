"""Peticiones y respuestas de alertas (ARCHITECTURE §5.3 `GET /v1/alerts` y §5.5 `/v1/admin/alerts`), BE-3.3.

- `AlertaEntrada`: cuerpo de `PUT /v1/admin/alerts/{id}` y de cada `upsert` de `sincronizar`. Ignora los campos de más
  (también `id`, `version`, `actualizado_en`…). `mensaje` se recorta (1–200) y pasa por `texto_admitido` (§4.4);
  `tipo`, `prioridad`, `radio_m` y `activa` ausentes **o `null`** toman su valor por defecto; las vigencias, con zona,
  se guardan en UTC **sin fracciones de segundo** (la resolución de §5.1) y, si están las dos, `hasta > desde`.
- `Alerta` (pública), `AlertaAdmin` (más `creado_en`, `creado_por`, `actualizado_por`), `AlertasRespuesta`
  (`GET /v1/alerts`) y `ListaAlertas` (`GET /v1/admin/alerts`): prohíben campos de más.
- `SincronizarPeticion`: `{"cambios": [Cambio…]}` (1–100). Cada `Cambio` es `{"op": "upsert", "alerta": {"id", …}}` o
  `{"op": "eliminar", "id"}`; si eso no se cumple (otro `op`, falta el `id` o no es un UUID) la petición entera es
  `422`. El resto de `alerta` se valida cambio por cambio en el servicio (un error da `estado = error` solo a ese).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.dominio.alertas import CAMBIOS_MAX, MENSAJE_MAX, MENSAJE_MIN, RADIO_MAX, RADIO_MIN, RADIO_POR_DEFECTO
from app.dominio.enumerados import PrioridadAlerta, TipoAlerta
from app.esquemas.comun import FechaConZona, FechaUtc, Referencia, texto_admitido

#: Valores de `estado` y `codigo` de un resultado de `sincronizar` (§5.5).
ESTADO_OK = "ok"
ESTADO_ERROR = "error"
CODIGO_VALIDACION = "VALIDACION"


def _sin_fracciones(valor: datetime | None) -> datetime | None:
    return valor.replace(microsecond=0) if valor is not None else None


class AlertaEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    mensaje: str
    tipo: TipoAlerta = TipoAlerta.otro
    prioridad: PrioridadAlerta = PrioridadAlerta.normal
    radio_m: int = Field(RADIO_POR_DEFECTO, ge=RADIO_MIN, le=RADIO_MAX)
    activa: bool = True
    vigencia_desde: FechaConZona | None = None
    vigencia_hasta: FechaConZona | None = None

    @field_validator("tipo", "prioridad", "radio_m", "activa", mode="before")
    @classmethod
    def _nulo_es_por_defecto(cls, valor: Any, info: ValidationInfo) -> Any:
        return cls.model_fields[info.field_name].default if valor is None else valor

    @field_validator("mensaje")
    @classmethod
    def _mensaje(cls, valor: str) -> str:
        texto = texto_admitido(valor).strip()
        if not MENSAJE_MIN <= len(texto) <= MENSAJE_MAX:
            raise ValueError(
                f"Debe tener entre {MENSAJE_MIN} y {MENSAJE_MAX} caracteres tras recortar los espacios de alrededor."
            )
        return texto

    @field_validator("vigencia_desde")
    @classmethod
    def _desde(cls, valor: datetime | None) -> datetime | None:
        return _sin_fracciones(valor)

    @field_validator("vigencia_hasta")
    @classmethod
    def _hasta(cls, valor: datetime | None, info: ValidationInfo) -> datetime | None:
        valor = _sin_fracciones(valor)
        desde = info.data.get("vigencia_desde")
        if valor is not None and desde is not None and valor <= desde:
            raise ValueError("Debe ser posterior a vigencia_desde (se comparan sin fracciones de segundo).")
        return valor

    def valores(self) -> dict[str, Any]:
        """Los campos que guarda la tabla (`dominio.alertas.CAMPOS`)."""
        return self.model_dump()


class Alerta(BaseModel):
    """`GET /v1/alerts` (§5.3)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    lat: float
    lng: float
    mensaje: str
    tipo: TipoAlerta
    prioridad: PrioridadAlerta
    radio_m: int
    activa: bool
    vigencia_desde: FechaUtc | None
    vigencia_hasta: FechaUtc | None
    actualizado_en: FechaUtc
    version: int


class AlertaAdmin(Alerta):
    """`Alerta` más `creado_en`, `creado_por` y `actualizado_por` (§5.5)."""

    creado_en: FechaUtc
    creado_por: Referencia
    actualizado_por: Referencia


class AlertasRespuesta(BaseModel):
    """`GET /v1/alerts`: la foto completa (`completo = true`) o las diferencias desde `desde`."""

    model_config = ConfigDict(extra="forbid")

    generado_en: FechaUtc
    completo: bool
    alertas: list[Alerta]
    eliminadas: list[uuid.UUID]


class ListaAlertas(BaseModel):
    """`GET /v1/admin/alerts`: sin paginar (las alertas son decenas); `total` = número de `items`."""

    model_config = ConfigDict(extra="forbid")

    items: list[AlertaAdmin]
    total: int


# --- sincronizar ---------------------------------------------------------------------------------------------------
class AlertaConId(BaseModel):
    """`alerta` de un `upsert`: el `id` se valida con la petición; el resto (los campos de `AlertaEntrada`), en el
    servicio, cambio por cambio."""

    model_config = ConfigDict(extra="allow")

    id: uuid.UUID

    def entrada(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Cambio(BaseModel):
    model_config = ConfigDict(extra="ignore")

    op: Literal["upsert", "eliminar"]
    alerta: AlertaConId | None = None
    id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _segun_op(self) -> Cambio:
        if self.op == "upsert" and self.alerta is None:
            raise ValueError("Con op = upsert hace falta `alerta` (con su `id`).")
        if self.op == "eliminar" and self.id is None:
            raise ValueError("Con op = eliminar hace falta `id`.")
        return self

    @property
    def alerta_id(self) -> uuid.UUID:
        if self.op == "upsert":
            assert self.alerta is not None  # noqa: S101 (lo garantiza _segun_op)
            return self.alerta.id
        assert self.id is not None  # noqa: S101
        return self.id


class SincronizarPeticion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cambios: list[Cambio] = Field(min_length=1, max_length=CAMBIOS_MAX)


class ResultadoCambio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    op: Literal["upsert", "eliminar"]
    estado: Literal["ok", "error"]
    codigo: str | None


class SincronizarRespuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generado_en: FechaUtc
    resultados: list[ResultadoCambio]
