"""Reglas de los lugares sin infraestructura (ARCHITECTURE §4.9, §5.3, §5.5), BE-3.1.

- `normalizar_nombre(texto)`: la forma con que se compara un nombre (`lugares.nombre_normalizado`, §5.7) y se busca
  con `q`: descomposición Unicode NFKD, sin marcas combinantes (tildes, diéresis, la virgulilla de la ñ), `casefold()`
  y los espacios de cualquier clase reducidos a uno, sin espacios alrededor. «Café  Norte», «CAFE NORTE» y
  «cafe norte» dan `cafe norte`; «Baño» y «Bano» dan `bano` (ADR-BE-17).
- Límites de `LugarEntrada` (§5.5), en caracteres y tras recortar los espacios de alrededor.
"""

from __future__ import annotations

import unicodedata

NOMBRE_MIN = 2
NOMBRE_MAX = 80
ALIAS_MAX_ELEMENTOS = 20
ALIAS_MAX = 60
DESCRIPCION_MAX = 300  # también `referencias`
#: Tope de `q` en `GET /v1/admin/places` (el mismo de `GET /v1/admin/videos`).
Q_MAX = 100
#: Decimales de `distancia_m` en `GET /v1/places`.
DECIMALES_DISTANCIA = 1


def normalizar_nombre(texto: str) -> str:
    """`texto` sin tildes, en minúsculas (`casefold`) y con los espacios reducidos (arriba). Puede quedar vacío."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_marcas.casefold().split())
