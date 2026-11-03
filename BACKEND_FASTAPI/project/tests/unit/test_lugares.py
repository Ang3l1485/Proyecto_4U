"""BE-3.1 sin base: nombre normalizado, geometría y validación de `LugarEntrada` (ARCHITECTURE §4.9, §5.5)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.dominio import geo
from app.dominio.lugares import normalizar_nombre
from app.esquemas.lugares import LugarEntrada


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Café Norte", "cafe norte"),
        ("CAFE NORTE", "cafe norte"),
        ("  café \t  NORTE\n", "cafe norte"),
        ("Baño", "bano"),
        ("Pingüino", "pinguino"),
        ("Straße", "strasse"),
        ("ﬁlosofía", "filosofia"),  # ligadura (compatibilidad NFKD)
        ("Bloque 19", "bloque 19"),  # espacio duro
        ("validacion-31-20261025-120000 Cafe Norte", "validacion-31-20261025-120000 cafe norte"),
        ("́́", ""),
    ],
)
def test_normalizar_nombre(texto, esperado):
    assert normalizar_nombre(texto) == esperado


def test_distancia_de_una_milesima_de_grado_en_el_ecuador():
    esperado = geo.RADIO_TIERRA_M * math.radians(0.001)  # 111,195 m
    assert geo.distancia_m(0.001, 0.001, 0.001, 0.002) == pytest.approx(esperado, rel=1e-6)
    assert geo.distancia_m(0.0, 0.0, 0.001, 0.0) == pytest.approx(esperado, rel=1e-9)
    assert geo.distancia_m(6.2, -75.57, 6.2, -75.57) == 0.0
    assert geo.distancia_m(6.2, -75.57, 6.201, -75.571) == pytest.approx(geo.distancia_m(6.201, -75.571, 6.2, -75.57))


@pytest.mark.parametrize(
    ("destino", "rumbo"),
    [((0.001, 0.0), 0.0), ((0.0, 0.001), 90.0), ((-0.001, 0.0), 180.0), ((0.0, -0.001), 270.0), ((0.0, 0.0), 0.0)],
)
def test_rumbo_grados(destino, rumbo):
    valor = geo.rumbo_grados(0.0, 0.0, *destino)
    assert 0.0 <= valor < 360.0
    assert valor == pytest.approx(rumbo, abs=1e-9)


def _entrada(**cambios):
    return {"nombre": "Biblioteca Central", "categoria": "biblioteca", "lat": 6.2009, "lng": -75.5783} | cambios


def test_entrada_minima_y_recortes():
    datos = LugarEntrada.model_validate(
        _entrada(nombre="  Biblioteca Central  ", alias=None, descripcion="   ", referencias=" Frente al lago ")
    )
    assert datos.nombre == "Biblioteca Central"
    assert datos.alias == []
    assert datos.descripcion is None
    assert datos.referencias == "Frente al lago"
    assert LugarEntrada.model_validate(_entrada()).alias == []
    con_alias = LugarEntrada.model_validate(_entrada(alias=[" la biblioteca ", "biblio"], id="x", imagen_url="y"))
    assert con_alias.alias == ["la biblioteca", "biblio"]
    assert not hasattr(con_alias, "imagen_url")


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"nombre": "a"}, "nombre"),
        ({"nombre": "  a  "}, "nombre"),
        ({"nombre": "x" * 81}, "nombre"),
        ({"nombre": "Ca\x00fe"}, "nombre"),
        ({"nombre": " ́́ "}, "nombre"),
        ({"categoria": "cocina"}, "categoria"),
        ({"lat": 90.5}, "lat"),
        ({"lng": -180.5}, "lng"),
        ({"lat": float("nan")}, "lat"),
        ({"alias": ["a"] * 21}, "alias"),
        ({"alias": ["ok", "   "]}, "alias"),
        ({"alias": ["x" * 61]}, "alias"),
        ({"descripcion": "x" * 301}, "descripcion"),
        ({"referencias": "\ud800"}, "referencias"),
    ],
)
def test_entrada_no_valida(cambios, campo):
    datos = _entrada(**cambios)
    with pytest.raises(ValidationError) as error:
        LugarEntrada.model_validate(datos)
    assert error.value.errors()[0]["loc"][0] == campo


def test_entrada_sin_campos_obligatorios():
    with pytest.raises(ValidationError) as error:
        LugarEntrada.model_validate({})
    assert {e["loc"][0] for e in error.value.errors()} == {"nombre", "categoria", "lat", "lng"}
