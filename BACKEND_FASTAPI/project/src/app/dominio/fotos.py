"""Reglas de una foto de consulta (ARCHITECTURE §5.3 y §5.5): BE-2.4 (`/v1/admin/diagnostico/vecinos`) y, con las mismas
reglas por foto, BE-3.2 (`/v1/localize`).

Una foto de consulta vale si su parte trae `Content-Type: image/jpeg`, no está vacía, pesa como mucho
`LOC_MAX_BYTES_FOTO` (§5.10) y empieza por la marca SOI de JPEG seguida de otro marcador (`FF D8 FF`). Aquí no se
decodifica: lo hace embeddings, que responde `400 IMAGEN_INVALIDA` si no puede (y la API lo devuelve como
`400 FOTOS_INVALIDAS`, §5.5). Los motivos son textos cortos sin datos de la imagen.
"""

from __future__ import annotations

TIPO_JPEG = "image/jpeg"
#: SOI (`FF D8`) y el comienzo del siguiente marcador (`FF`): todo JPEG, también los multi-imagen (MPO), empieza así.
FIRMA_JPEG = b"\xff\xd8\xff"


def motivo_foto_no_valida(tipo: str, datos: bytes, max_bytes: int) -> str | None:
    """`None` si la foto vale; si no, el motivo (en este orden: tipo, vacía, tamaño, firma)."""
    if tipo != TIPO_JPEG:
        return f"tipo {tipo or 'desconocido'}: se espera {TIPO_JPEG}"
    if not datos:
        return "la foto está vacía"
    if len(datos) > max_bytes:
        return f"la foto pesa {len(datos)} bytes (máximo {max_bytes})"
    if not datos.startswith(FIRMA_JPEG):
        return "no es un JPEG (no empieza por FF D8 FF)"
    return None
