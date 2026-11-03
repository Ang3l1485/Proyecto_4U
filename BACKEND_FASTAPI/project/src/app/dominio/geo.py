"""Geometría sobre la esfera, sin infraestructura (ARCHITECTURE §4.9), desde BE-3.1.

- `distancia_m(lat1, lng1, lat2, lng2)`: distancia de círculo máximo (haversine) en metros, con el radio medio de la
  Tierra `RADIO_TIERRA_M` (6 371 008,8 m). A las distancias del campus (cientos de metros) el error frente al
  elipsoide WGS84 es < 0,5 %. La usa `GET /v1/places` (BE-3.1) y la usará BE-3.2 (lugar cercano y referencias, §4.10).
- `rumbo_grados(lat1, lng1, lat2, lng2)`: rumbo inicial del punto 1 al 2, en grados [0, 360), 0 = norte verdadero,
  sentido horario (§5.1, ADR-BE-12). Para `referencias[].rumbo_grados` de BE-3.2. Entre dos puntos iguales, 0.
"""

from __future__ import annotations

import math

RADIO_TIERRA_M = 6_371_008.8


def distancia_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    dfi = fi2 - fi1
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dfi / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(dlambda / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def rumbo_grados(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lng2 - lng1)
    x = math.sin(dlambda) * math.cos(fi2)
    y = math.cos(fi1) * math.sin(fi2) - math.sin(fi1) * math.cos(fi2) * math.cos(dlambda)
    if x == 0 and y == 0:
        return 0.0
    rumbo = math.degrees(math.atan2(x, y)) % 360.0
    return 0.0 if rumbo >= 360.0 else rumbo  # -1e-17 % 360 da 360.0 en coma flotante
