"""`app.dominio.multipart` y `app.dominio.fotos` (BE-2.4, ARCHITECTURE §4.8): el cuerpo multipart en memoria y las
reglas de una foto de consulta."""

from __future__ import annotations

import os

import httpx
import pytest

from app.dominio.fotos import FIRMA_JPEG, motivo_foto_no_valida
from app.dominio.multipart import MultipartInvalido, NoEsMultipart, Parte, partes_multipart


def _de_httpx(files, data=None) -> tuple[str, bytes]:
    """Lo que manda httpx (el cliente de la herramienta de evaluación y de los validadores)."""
    peticion = httpx.Request("POST", "http://x/", files=files, data=data)
    return peticion.headers["content-type"], peticion.read()


def test_lee_lo_que_manda_httpx_con_bytes_binarios():
    foto = FIRMA_JPEG + os.urandom(5000) + b"\r\n--no-es-el-limite\r\n\r\n" + bytes(range(256))
    tipo, cuerpo = _de_httpx([("foto", ("consulta.jpg", foto, "image/jpeg"))], data={"nota": "hola"})
    partes = partes_multipart(tipo, cuerpo)
    assert partes == [
        Parte(nombre="nota", archivo=None, tipo="text/plain", datos=b"hola"),
        Parte(nombre="foto", archivo="consulta.jpg", tipo="image/jpeg", datos=foto),
    ]


def test_parte_vacia_preambulo_epilogo_y_tipo_con_parametros():
    cuerpo = (
        b"preambulo\r\n--b0\r\n"
        b'Content-Disposition: form-data; name="foto"; filename="a b.jpg"\r\n'
        b"Content-Type: Image/JPEG; charset=binary\r\n\r\n"
        b"\r\n--b0\r\n"
        b'content-disposition: form-data; name="x"\r\n\r\n'
        b"1\r\n--b0--\r\nepilogo"
    )
    foto, x = partes_multipart('multipart/form-data; boundary="b0"', cuerpo)
    assert (foto.nombre, foto.archivo, foto.tipo, foto.datos) == ("foto", "a b.jpg", "image/jpeg", b"")
    assert (x.nombre, x.tipo, x.datos) == ("x", "text/plain", b"1")


def test_sin_partes():
    assert partes_multipart("multipart/form-data; boundary=b", b"--b--\r\n") == []


@pytest.mark.parametrize("tipo", [None, "", "application/json", "image/jpeg", "multipart/mixed; boundary=b"])
def test_lo_que_no_es_multipart_form_data(tipo):
    with pytest.raises(NoEsMultipart):
        partes_multipart(tipo, b"--b--")


@pytest.mark.parametrize(
    ("tipo", "cuerpo"),
    [
        ("multipart/form-data", b"--b--"),  # sin boundary
        ("multipart/form-data; boundary=" + "x" * 71, b"--b--"),  # boundary de más de 70
        ("multipart/form-data; boundary=b", b"nada que ver"),  # sin el primer delimitador
        ("multipart/form-data; boundary=b", b'--b\r\nContent-Disposition: form-data; name="f"\r\n\r\ndatos'),  # sin fin
        ("multipart/form-data; boundary=b", b"--b\r\nContent-Type: image/jpeg\r\n\r\nx\r\n--b--"),  # sin disposición
        ("multipart/form-data; boundary=b", b"--b\r\nContent-Disposition: form-data\r\n\r\nx\r\n--b--"),  # sin name
        ("multipart/form-data; boundary=b", b'--b\r\nContent-Disposition: attachment; name="f"\r\n\r\nx\r\n--b--'),
        ("multipart/form-data; boundary=b", b"--bbasura\r\n\r\nx\r\n--b--"),  # delimitador mal terminado
        ("multipart/form-data; boundary=b", b'--b\r\nContent-Disposition: form-data; name="f"\r\n--b--'),  # sin fin
        ("multipart/form-data; boundary=b", b"--b\r\nsin dos puntos\r\n\r\nx\r\n--b--"),
    ],
)
def test_multipart_mal_formado(tipo, cuerpo):
    with pytest.raises(MultipartInvalido):
        partes_multipart(tipo, cuerpo)


def test_nombre_codificado_rfc2231():
    cuerpo = b"--b\r\nContent-Disposition: form-data; name*=utf-8''foto\r\n\r\n\xff\xd8\xff\r\n--b--"
    [parte] = partes_multipart("multipart/form-data; boundary=b", cuerpo)
    assert parte.nombre == "foto"


# --- app.dominio.fotos ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tipo", "datos", "motivo"),
    [
        ("image/jpeg", FIRMA_JPEG + b"x" * 10, None),
        ("image/png", FIRMA_JPEG, "tipo image/png: se espera image/jpeg"),
        ("", FIRMA_JPEG, "tipo desconocido: se espera image/jpeg"),
        ("image/jpeg", b"", "la foto está vacía"),
        ("image/jpeg", FIRMA_JPEG + b"x" * 98, "la foto pesa 101 bytes (máximo 100)"),
        ("image/jpeg", b"\x89PNG\r\n", "no es un JPEG (no empieza por FF D8 FF)"),
        ("image/jpeg", b"\xff\xd8", "no es un JPEG (no empieza por FF D8 FF)"),
    ],
)
def test_motivo_foto_no_valida(tipo, datos, motivo):
    assert motivo_foto_no_valida(tipo, datos, 100) == motivo
