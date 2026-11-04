"""Ayudas de BE-2.4 en `src/ops/comun.py` (backend ARCHITECTURE §5.11): fotos sintéticas, `pedir_vecinos`,
`mensajes_log` y `lote_hecho`."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest

import comun

Image = pytest.importorskip("PIL.Image")


def _abrir(datos: bytes):
    imagen = Image.open(io.BytesIO(datos))
    imagen.load()
    return imagen


def test_jpeg_patron_en_color_determinista_y_distinto_por_patron():
    fotos = [comun.jpeg_patron(1000 + i) for i in range(4)]
    for datos in fotos:
        imagen = _abrir(datos)
        assert (imagen.format, imagen.size, imagen.mode) == ("JPEG", (1024, 768), "RGB")
        assert datos.startswith(b"\xff\xd8\xff") and 5_000 < len(datos) < 1_572_864
    assert comun.jpeg_patron(1001) == fotos[1] and len(set(fotos)) == 4
    # colores distintos: el patrón no es gris
    assert len(_abrir(fotos[1]).getcolors(1 << 20)) > 10


def test_jpeg_ruido_pesa_menos_que_loc_max_bytes_foto():
    datos = comun.jpeg_ruido(7)
    assert _abrir(datos).size == (512, 384) and len(datos) < 1_572_864
    assert comun.jpeg_ruido(7) == datos and comun.jpeg_ruido(8) != datos


def test_jpeg_relleno_y_png():
    datos = comun.jpeg_relleno(1_677_722)
    assert len(datos) == 1_677_722 and datos.startswith(b"\xff\xd8\xff")
    assert _abrir(datos).format == "JPEG"  # el relleno va tras el EOI
    assert _abrir(comun.png_sintetico()).format == "PNG"
    with pytest.raises(comun.Falla):
        comun.jpeg_relleno(10)


class Http:
    def __init__(self) -> None:
        self.peticiones: list[tuple[str, str, dict]] = []

    def request(self, metodo, url, **kwargs):
        self.peticiones.append((metodo, url, kwargs))
        return type("R", (), {"status_code": 200, "headers": {}, "json": lambda self: {}, "text": "{}"})()

    def close(self) -> None:
        pass


def test_pedir_vecinos_manda_la_parte_foto_y_k():
    http = Http()
    api = comun.ClienteApi("https://x/v1", http=http)
    comun.pedir_vecinos(api, "tok", b"\xff\xd8\xffdatos", k=10)
    comun.pedir_vecinos(api, None, b"png", k=None, tipo="image/png", parte="otra")
    (m1, u1, k1), (_, _, k2) = http.peticiones
    assert (m1, u1) == ("POST", "https://x/v1/admin/diagnostico/vecinos")
    assert k1["params"] == {"k": 10} and k1["headers"] == {"Authorization": "Bearer tok"}
    assert k1["files"] == [("foto", ("consulta.jpg", b"\xff\xd8\xffdatos", "image/jpeg"))]
    assert k2["params"] == {} and k2["headers"] == {}
    assert k2["files"] == [("otra", ("consulta.jpg", b"png", "image/png"))]


class Logs:
    def __init__(self, paginas, error=None) -> None:
        self.paginas, self.error, self.llamadas = paginas, error, []

    def filter_log_events(self, **argumentos):
        self.llamadas.append(argumentos)
        if self.error:
            raise self.error
        return self.paginas[len(self.llamadas) - 1]


def test_mensajes_log_recorre_todas_las_paginas_sin_patron():
    logs = Logs([{"events": [{"message": "a"}], "nextToken": "t1"}, {"events": [{"message": "b"}, {"message": "c"}]}])
    desde = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    assert comun.mensajes_log(logs, comun.LOG_API, desde) == ["a", "b", "c"]
    assert logs.llamadas[0] == {"logGroupName": "/campus-locator/dev/api", "startTime": int(desde.timestamp() * 1000)}
    assert logs.llamadas[1]["nextToken"] == "t1"


def test_mensajes_log_sin_permiso_es_error_de_configuracion():
    from botocore.exceptions import ClientError

    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "FilterLogEvents")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.mensajes_log(Logs([], error), comun.LOG_EMBEDDING, datetime.now(UTC))


def test_lote_hecho_lee_la_tabla_de_estado():
    tabla = "| BE-2.2 | 2 | Hecho | [2-2](x) | `3b01b68` |\n| BE-2.4 | 2 | En curso | … |"
    assert comun.lote_hecho(tabla, "BE-2.2")
    assert not comun.lote_hecho(tabla, "BE-2.4")
    assert not comun.lote_hecho("| BE-2.2 | Worker de ingesta | BE-2.1 | BE-2.1 |", "BE-2.2")
