"""`app.dominio.imagenes.preparar`: validación, EXIF, miniatura y copia reducida (ARCHITECTURE §4.6, paso 3)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.dominio.imagenes import ImagenNoValida, preparar

PARAMETROS = {
    "max_bytes": 4_194_304,
    "lado_min": 320,
    "lado_miniatura": 320,
    "calidad_miniatura": 80,
    "lado_embedding": 1024,
}


def jpeg(ancho: int, alto: int, orientacion: int | None = None, formato: str = "JPEG") -> bytes:
    imagen = Image.new("RGB", (ancho, alto), (120, 80, 40))
    for x in range(0, ancho, 7):  # algo de detalle para que no sea un color plano
        imagen.putpixel((x, x % alto), (255, 255, 255))
    salida = io.BytesIO()
    if orientacion is not None:
        exif = Image.Exif()
        exif[0x0112] = orientacion
        imagen.save(salida, format=formato, exif=exif)
    else:
        imagen.save(salida, format=formato)
    return salida.getvalue()


def _abrir(datos: bytes) -> Image.Image:
    imagen = Image.open(io.BytesIO(datos))
    imagen.load()
    return imagen


def test_foto_valida_da_miniatura_y_copia_reducida():
    preparada = preparar(jpeg(2048, 1536), **PARAMETROS)
    assert (preparada.ancho, preparada.alto) == (2048, 1536)
    mini, reducida = _abrir(preparada.miniatura), _abrir(preparada.reducida)
    assert mini.format == "JPEG" and mini.size == (320, 240)
    assert reducida.format == "JPEG" and reducida.size == (1024, 768)


def test_foto_pequena_no_se_amplia():
    preparada = preparar(jpeg(640, 480), **PARAMETROS)
    assert _abrir(preparada.reducida).size == (640, 480)
    assert _abrir(preparada.miniatura).size == (320, 240)


def test_orientacion_exif_se_aplica_y_la_copia_sale_sin_exif():
    preparada = preparar(jpeg(1024, 768, orientacion=6), **PARAMETROS)  # 6 = girar 90°: queda vertical
    assert (preparada.ancho, preparada.alto) == (768, 1024)
    reducida = _abrir(preparada.reducida)
    assert reducida.size == (768, 1024)
    assert reducida.getexif().get(0x0112) is None  # embeddings no la vuelve a girar


@pytest.mark.parametrize(
    ("datos", "motivo"),
    [
        (b"validacion-no-es-jpeg", "no es un JPEG decodificable"),
        (jpeg(1024, 768, formato="PNG"), "no es un JPEG decodificable"),
        (jpeg(1024, 768)[:600], "no es un JPEG decodificable"),  # truncado
        (jpeg(400, 300), "lado menor 300 px (mínimo 320)"),
    ],
)
def test_fotos_que_no_valen(datos, motivo):
    with pytest.raises(ImagenNoValida) as error:
        preparar(datos, **PARAMETROS)
    assert error.value.motivo == motivo


def mpo(orientacion: int | None = None) -> bytes:
    """JPEG multi-imagen (MPO) de 2 imágenes: la foto (1024×768) y una vista de 512×384, como algunas cámaras."""
    foto = Image.new("RGB", (1024, 768), (200, 40, 40))
    vista = Image.new("RGB", (512, 384), (40, 40, 200))
    salida = io.BytesIO()
    extra = {}
    if orientacion is not None:
        exif = Image.Exif()
        exif[0x0112] = orientacion
        extra["exif"] = exif
    foto.save(salida, format="MPO", save_all=True, append_images=[vista], **extra)
    return salida.getvalue()


def test_jpeg_multi_imagen_mpo_usa_la_primera_imagen():
    datos = mpo()
    assert Image.open(io.BytesIO(datos)).format == "MPO"  # Pillow no lo abre como JPEG
    preparada = preparar(datos, **PARAMETROS)
    assert (preparada.ancho, preparada.alto) == (1024, 768)  # la primera, no la vista de 512×384
    reducida = _abrir(preparada.reducida)
    assert reducida.format == "JPEG" and reducida.size == (1024, 768)
    assert getattr(reducida, "n_frames", 1) == 1  # la copia que va a embeddings es un JPEG de una sola imagen
    assert reducida.getpixel((10, 10))[0] > 150  # el color de la foto, no el de la vista
    assert _abrir(preparada.miniatura).size == (320, 240)


def test_mpo_con_orientacion_exif_se_gira_como_un_jpeg():
    preparada = preparar(mpo(orientacion=6), **PARAMETROS)
    assert (preparada.ancho, preparada.alto) == (768, 1024)
    assert _abrir(preparada.reducida).getexif().get(0x0112) is None


def test_el_jpeg_sintetico_de_los_validadores_vale():
    import comun

    preparada = preparar(comun.jpeg_sintetico(1024, 768, semilla=7), **PARAMETROS)  # escala de grises, solo DC
    assert (preparada.ancho, preparada.alto) == (1024, 768)
    assert _abrir(preparada.reducida).mode == "RGB"


def test_demasiado_grande_no_se_decodifica():
    with pytest.raises(ImagenNoValida, match=r"demasiado grande: 11 bytes \(máximo 10\)"):
        preparar(b"x" * 11, **(PARAMETROS | {"max_bytes": 10}))
