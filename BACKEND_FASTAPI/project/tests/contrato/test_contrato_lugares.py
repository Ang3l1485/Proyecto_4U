"""Contrato de BE-3.1: los ejemplos y reglas de `GET /v1/places` (ARCHITECTURE §5.3) y de `/v1/admin/places` (§5.5),
el código `NOMBRE_DUPLICADO` (§5.6) y las rutas del OpenAPI coinciden con los esquemas y la app. Las alertas (BE-3.3)
tienen su propia prueba (`test_contrato_alertas.py`). Se omite si el documento no está (p. ej. con `project/` copiado
solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.dominio.enumerados import CategoriaLugar
from app.dominio.lugares import ALIAS_MAX, ALIAS_MAX_ELEMENTOS, DESCRIPCION_MAX, NOMBRE_MAX, NOMBRE_MIN
from app.errores import MENSAJE_POR_CODIGO
from app.esquemas.lugares import LugarAdmin, LugarEntrada, LugarPublico
from app.main import crear_app

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def _ejemplos(seccion: str) -> list:
    return [json.loads(bloque) for bloque in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]


def test_ejemplo_y_categorias_de_get_places(documento):
    seccion = _seccion(documento, "#### `GET /v1/places`", "#### `GET /v1/alerts`")
    [publico] = _ejemplos(seccion)
    assert set(publico) == set(LugarPublico.model_fields)
    categorias = re.search(r"`categoria` ∈ \{([^}]*)\}", seccion).group(1)
    assert re.findall(r"`([a-z]+)`", categorias) == [c.value for c in CategoriaLugar]
    assert "radio medio de la Tierra 6 371 008,8 m" in seccion and "1 decimal" in seccion


def test_ejemplos_de_admin_places(documento):
    seccion = _seccion(documento, "#### Lugares: `/v1/admin/places` (BE-3.1)", "#### `POST /v1/admin/diagnostico/")
    entrada, admin = _ejemplos(seccion)
    assert set(entrada) == set(LugarEntrada.model_fields)
    LugarEntrada.model_validate(entrada)
    assert set(admin) == set(LugarAdmin.model_fields)
    assert set(LugarAdmin.model_fields) == (set(LugarPublico.model_fields) - {"distancia_m"}) | {
        "creado_en",
        "actualizado_en",
        "total_fotos",
    }


def test_limites_de_lugar_entrada(documento):
    seccion = _seccion(documento, "`LugarEntrada`: `nombre`", "`AlertaEntrada`")
    assert f"`nombre` ({NOMBRE_MIN}–{NOMBRE_MAX})" in seccion
    assert f"`alias` (≤ {ALIAS_MAX_ELEMENTOS} textos de ≤ {ALIAS_MAX})" in seccion
    assert f"`descripcion` (≤ {DESCRIPCION_MAX})" in seccion and f"`referencias` (≤ {DESCRIPCION_MAX})" in seccion
    assert "`409 NOMBRE_DUPLICADO`" in seccion


def test_nombre_duplicado_en_5_6_y_en_errores(documento):
    tabla = _seccion(documento, "### 5.6 ", "### 5.7 ")
    assert "`NOMBRE_DUPLICADO`" in tabla
    assert "NOMBRE_DUPLICADO" in MENSAJE_POR_CODIGO


def test_rutas_del_openapi():
    rutas = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"]
    assert set(rutas["/v1/places"]) == {"get"}
    assert "security" not in rutas["/v1/places"]["get"]
    assert set(rutas["/v1/admin/places"]) == {"get", "post"}
    assert set(rutas["/v1/admin/places/{lugar_id}"]) == {"put", "delete"}
    assert all(
        op.get("security")
        for metodos in ("/v1/admin/places", "/v1/admin/places/{lugar_id}")
        for op in rutas[metodos].values()
    )
