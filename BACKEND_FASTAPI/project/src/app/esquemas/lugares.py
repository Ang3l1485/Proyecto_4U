"""Peticiones y respuestas de lugares (ARCHITECTURE §5.3 `GET /v1/places` y §5.5 `/v1/admin/places`), BE-3.1.

- `LugarEntrada`: cuerpo de `POST` y `PUT /v1/admin/places`. Ignora los campos de más (también `id`, `imagen_url`…);
  todo texto pasa por `texto_admitido` (§4.4) y se recorta. `alias` ausente o `null` = `[]`; `descripcion` y
  `referencias` vacías o solo espacios = `null`.
- `LugarPublico` (con `distancia_m`) y `LugarAdmin` (con `creado_en`, `actualizado_en` y `total_fotos`): prohíben
  campos de más.
- `ListaLugares[T]`: `{items, total}` sin paginación (los lugares son decenas).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dominio.enumerados import CategoriaLugar
from app.dominio.lugares import (
    ALIAS_MAX,
    ALIAS_MAX_ELEMENTOS,
    DESCRIPCION_MAX,
    NOMBRE_MAX,
    NOMBRE_MIN,
    normalizar_nombre,
)
from app.esquemas.comun import FechaUtc, texto_admitido


def _texto_opcional(valor: str | None, maximo: int) -> str | None:
    if valor is None:
        return None
    texto = texto_admitido(valor).strip()
    if not texto:
        return None
    if len(texto) > maximo:
        raise ValueError(f"Debe tener como máximo {maximo} caracteres tras recortar los espacios.")
    return texto


class LugarEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str
    categoria: CategoriaLugar
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    alias: list[str] = Field(default_factory=list, max_length=ALIAS_MAX_ELEMENTOS)
    descripcion: str | None = None
    referencias: str | None = None

    @field_validator("alias", mode="before")
    @classmethod
    def _alias_nulo(cls, valor: object) -> object:
        return [] if valor is None else valor

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        texto = texto_admitido(valor).strip()
        if not NOMBRE_MIN <= len(texto) <= NOMBRE_MAX:
            raise ValueError(
                f"Debe tener entre {NOMBRE_MIN} y {NOMBRE_MAX} caracteres tras recortar los espacios de alrededor."
            )
        if not normalizar_nombre(texto):
            raise ValueError("No puede quedar vacío al quitar las tildes y los espacios.")
        return texto

    @field_validator("alias")
    @classmethod
    def _alias(cls, valor: list[str]) -> list[str]:
        resultado = []
        for texto in valor:
            texto = texto_admitido(texto).strip()
            if not texto:
                raise ValueError("Ningún alias puede estar vacío.")
            if len(texto) > ALIAS_MAX:
                raise ValueError(f"Cada alias debe tener como máximo {ALIAS_MAX} caracteres tras recortar espacios.")
            resultado.append(texto)
        return resultado

    @field_validator("descripcion", "referencias")
    @classmethod
    def _textos(cls, valor: str | None) -> str | None:
        return _texto_opcional(valor, DESCRIPCION_MAX)


class _LugarBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    nombre: str
    categoria: CategoriaLugar
    lat: float
    lng: float
    alias: list[str]
    descripcion: str | None
    referencias: str | None
    imagen_url: str | None


class LugarPublico(_LugarBase):
    """`GET /v1/places`: `distancia_m` en metros con 1 decimal, o `null` sin posición."""

    distancia_m: float | None


class LugarAdmin(_LugarBase):
    """`LugarPublico` sin `distancia_m`, más `creado_en`, `actualizado_en` y `total_fotos` (§5.5)."""

    creado_en: FechaUtc
    actualizado_en: FechaUtc
    total_fotos: int


class ListaLugares[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int
