"""Alertas (ARCHITECTURE §4.11, §5.3 `GET /v1/alerts`, §5.5 `/v1/admin/alerts`), BE-3.3. Python puro (§4.1).

- Límites de `AlertaEntrada` (§5.5): `MENSAJE_MAX` (200, tras recortar), `RADIO_MIN`/`RADIO_MAX` (5–100) y
  `RADIO_POR_DEFECTO` (15); `CAMBIOS_MAX` (100) de `sincronizar`; `Q_MAX` (100) de `GET /v1/admin/alerts?q=`.
- `CAMPOS`: los 9 campos de `AlertaEntrada` que guarda la tabla, en el orden de `detalle.cambios` de la auditoría.
- `MARGEN_DESDE_S` (60): `GET /v1/alerts?desde=` devuelve lo modificado desde `desde − 60 s`. `actualizado_en` es el
  `now()` de la transacción que escribe, que puede confirmarse después de que otra lectura tome su foto y su
  `generado_en`; sin margen, ese cambio no saldría nunca en una diferencia. Repetir un cambio ya aplicado no cambia la
  caché de la app (reemplaza por `id`).
- `leer_if_match(texto)` → versión (`ValueError` con el motivo); `campos_cambiados(guardado, nuevo)`;
  `pide_foto_completa(desde, ahora, dias)`; `corte_desde(desde)`; `coincide(mensaje, q)` (la búsqueda del panel, sin
  tildes ni mayúsculas, con la regla de nombres de lugares).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from app.dominio.lugares import normalizar_nombre

MENSAJE_MIN = 1
MENSAJE_MAX = 200
RADIO_MIN = 5
RADIO_MAX = 100
RADIO_POR_DEFECTO = 15
CAMBIOS_MAX = 100
Q_MAX = 100
VERSION_MAX = 2_147_483_647  # `alertas.version` es `integer`
MARGEN_DESDE_S = 60

#: Campos de `AlertaEntrada` que guarda la tabla (los que lista `detalle.cambios` de `alerta.upsert`).
CAMPOS = ("lat", "lng", "mensaje", "tipo", "prioridad", "radio_m", "activa", "vigencia_desde", "vigencia_hasta")

_IF_MATCH = re.compile(r'"(\d{1,10})"|(\d{1,10})')
MOTIVO_IF_MATCH = 'Debe ser la versión de la alerta: un entero ≥ 1, solo o entre comillas (p. ej. 3 o "3").'


def leer_if_match(texto: str) -> int:
    """`If-Match: 3` o `If-Match: "3"` → 3. Otro valor (vacío, `*`, varias versiones, `W/"3"`, 0) → `ValueError`."""
    coincidencia = _IF_MATCH.fullmatch(texto.strip())
    if coincidencia is None:
        raise ValueError(MOTIVO_IF_MATCH)
    version = int(coincidencia.group(1) or coincidencia.group(2))
    if not 1 <= version <= VERSION_MAX:
        raise ValueError(MOTIVO_IF_MATCH)
    return version


def campos_cambiados(guardado: Any, nuevo: Mapping[str, Any]) -> list[str]:
    """Los de `CAMPOS` en que `nuevo` (un dict) difiere de `guardado` (una fila o un objeto con esos atributos)."""
    return [campo for campo in CAMPOS if getattr(guardado, campo) != nuevo[campo]]


def corte_desde(desde: datetime) -> datetime:
    """Desde cuándo se buscan cambios para un `desde` (`MARGEN_DESDE_S` antes)."""
    return desde - timedelta(seconds=MARGEN_DESDE_S)


def pide_foto_completa(desde: datetime | None, ahora: datetime, dias_tombstone: int) -> bool:
    """¿`GET /v1/alerts` responde la foto completa? Sin `desde`; con uno posterior a `ahora` (no salió de un
    `generado_en`: la diferencia podría saltarse cambios); o con uno cuyo corte es anterior a `ahora −
    ALERTAS_TOMBSTONE_DIAS` (los *tombstones* de entonces ya pueden estar purgados)."""
    if desde is None or desde > ahora:
        return True
    return corte_desde(desde) < ahora - timedelta(days=dias_tombstone)


def coincide(mensaje: str, q: str | None) -> bool:
    """¿`q` está contenido en `mensaje`, sin tildes, mayúsculas ni espacios de más? `q` vacío = sin filtro."""
    texto = normalizar_nombre(q) if q is not None else ""
    return not texto or texto in normalizar_nombre(mensaje)
