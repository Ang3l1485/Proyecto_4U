"""Validación y derivados de una foto del dataset (ARCHITECTURE §4.6, paso 3), sin red ni base.

`preparar(datos, ...)` decodifica el JPEG con Pillow, lo valida, aplica la orientación EXIF y devuelve sus
dimensiones (ya orientadas), la miniatura (`thumbs/…`) y la copia reducida que se envía a embeddings. Lo que no es una
foto válida lanza `ImagenNoValida(motivo)`: el `worker` la deja en `error` con ese motivo (error permanente).

Los motivos son textos fijos (el `error` de `ImagenAdmin`, §5.5); ninguno lleva bytes de la imagen.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

#: Máximo de `smallint` (`imagenes.ancho` y `alto`, §5.7).
LADO_MAX_ESQUEMA = 32767
#: Calidad JPEG de la copia reducida que va al modelo (§4.6).
CALIDAD_REDUCIDA = 90

MOTIVO_NO_JPEG = "no es un JPEG decodificable"
#: Formatos de Pillow que se aceptan: `MPO` es un JPEG con varias imágenes (extensión MPF de algunas cámaras) y se
#: procesa su primera imagen como un JPEG normal (EXIF incluido).
FORMATOS_ADMITIDOS = ("JPEG", "MPO")


class ImagenNoValida(Exception):
    """La foto no se puede usar (error permanente); `motivo` va a `imagenes.error`."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


@dataclass(frozen=True)
class ImagenPreparada:
    ancho: int  # tras corregir EXIF
    alto: int
    miniatura: bytes  # JPEG, lado mayor ≤ MINIATURA_LADO_PX
    reducida: bytes  # JPEG calidad 90, lado mayor ≤ WORKER_LADO_EMBEDDING_PX, sin EXIF (ya orientada)


def motivo_demasiado_grande(n_bytes: int, max_bytes: int) -> str:
    return f"demasiado grande: {n_bytes} bytes (máximo {max_bytes})"


def _jpeg(imagen: Image.Image, calidad: int) -> bytes:
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=calidad)  # sin `exif=`: la copia sale sin orientación EXIF
    return salida.getvalue()


def _reducir(imagen: Image.Image, lado_max: int) -> Image.Image:
    """Copia con el lado mayor ≤ `lado_max` (LANCZOS, proporción conservada); si ya cabe, la misma imagen."""
    if max(imagen.size) <= lado_max:
        return imagen
    copia = imagen.copy()
    copia.thumbnail((lado_max, lado_max), Image.Resampling.LANCZOS)
    return copia


def preparar(
    datos: bytes,
    *,
    max_bytes: int,
    lado_min: int,
    lado_miniatura: int,
    calidad_miniatura: int,
    lado_embedding: int,
) -> ImagenPreparada:
    """Valida (≤ `max_bytes`, JPEG decodificable —también `MPO`, de la que se usa la primera imagen—, lado menor ≥
    `lado_min` tras EXIF) y genera miniatura y copia reducida (las dos, JPEG de una sola imagen). Las bombas de
    descompresión (más de `Image.MAX_IMAGE_PIXELS`, ~89,5 MP) son «no es un JPEG decodificable», igual que un
    archivo truncado."""
    if len(datos) > max_bytes:
        raise ImagenNoValida(motivo_demasiado_grande(len(datos), max_bytes))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(datos)) as original:
                if original.format not in FORMATOS_ADMITIDOS:
                    raise ImagenNoValida(MOTIVO_NO_JPEG)
                if original.format == "MPO":
                    original.seek(0)  # JPEG multi-imagen: solo la primera (la foto); las demás son vistas o mapas
                original.load()
                orientada = ImageOps.exif_transpose(original)
                rgb = orientada.convert("RGB")
    except ImagenNoValida:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning):
        raise ImagenNoValida(MOTIVO_NO_JPEG) from None
    ancho, alto = rgb.size
    if min(ancho, alto) < lado_min:
        raise ImagenNoValida(f"lado menor {min(ancho, alto)} px (mínimo {lado_min})")
    if max(ancho, alto) > LADO_MAX_ESQUEMA:
        raise ImagenNoValida(f"lado mayor {max(ancho, alto)} px (máximo {LADO_MAX_ESQUEMA})")
    miniatura = _jpeg(_reducir(rgb, lado_miniatura), calidad_miniatura)
    reducida = _jpeg(_reducir(rgb, lado_embedding), CALIDAD_REDUCIDA)
    return ImagenPreparada(ancho=ancho, alto=alto, miniatura=miniatura, reducida=reducida)
