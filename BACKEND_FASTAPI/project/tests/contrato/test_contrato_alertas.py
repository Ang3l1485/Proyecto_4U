"""Contrato de BE-3.3: el ejemplo y las reglas de `GET /v1/alerts` (ARCHITECTURE §5.3), las filas de
`/v1/admin/alerts` y `AlertaEntrada` (§5.5), `CONFLICTO_VERSION` (§5.6) y las rutas del OpenAPI coinciden con los
esquemas. Se omite si el documento no está (p. ej. con `project/` copiado solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.dominio.alertas import (
    CAMBIOS_MAX,
    MARGEN_DESDE_S,
    MENSAJE_MAX,
    RADIO_MAX,
    RADIO_MIN,
    RADIO_POR_DEFECTO,
)
from app.dominio.enumerados import PrioridadAlerta, TipoAlerta
from app.errores import MENSAJE_POR_CODIGO
from app.esquemas.alertas import Alerta, AlertaAdmin, AlertaEntrada, AlertasRespuesta
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
    return [
        json.loads(bloque.replace("Alerta…", '"…"')) for bloque in re.findall(r"```json\n(.*?)\n```", seccion, re.S)
    ]


def test_ejemplos_de_get_alerts(documento):
    seccion = _seccion(documento, "#### `GET /v1/alerts`", "#### Endpoints reservados")
    respuesta, alerta = _ejemplos(seccion)
    assert set(respuesta) == set(AlertasRespuesta.model_fields)
    assert set(alerta) == set(Alerta.model_fields)
    modelo = Alerta.model_validate(alerta | {"id": "1d6e0000-0000-4000-8000-000000000000"})
    assert modelo.model_dump(mode="json")["actualizado_en"] == alerta["actualizado_en"]  # ya en UTC, Z, sin fracciones


def test_tipos_prioridades_y_radio(documento):
    seccion = _seccion(documento, "#### `GET /v1/alerts`", "#### Endpoints reservados")
    tipos = re.search(r"`tipo` ∈ \{([^}]*)\}", seccion).group(1)
    assert re.findall(r"`([a-z]+)`", tipos) == [t.value for t in TipoAlerta]
    prioridades = re.search(r"`prioridad` ∈ \{([^}]*)\}", seccion).group(1)
    assert re.findall(r"`([a-z]+)`", prioridades) == [p.value for p in PrioridadAlerta]
    assert f"`radio_m` entero en [{RADIO_MIN}, {RADIO_MAX}]" in seccion
    assert "`MARGEN_DESDE_S`" in seccion and f"`desde` − {MARGEN_DESDE_S} s" in seccion


def test_alerta_entrada_y_alerta_admin(documento):
    seccion = _seccion(documento, "`AlertaEntrada`: `lat`", "#### `GET /v1/admin/stats` (BE-2.3)")
    assert f"`mensaje` (1–{MENSAJE_MAX} tras recortar)" in seccion
    assert "`tipo` (por defecto `otro`)" in seccion and "`prioridad` (por defecto" in seccion
    assert f"(5–100, por defecto {RADIO_POR_DEFECTO})" in seccion and "`activa` (por defecto `true`)" in seccion
    assert "`hasta > desde`" in seccion
    campos = re.findall(r"`([a-z_]+)`", seccion[: seccion.index("En `sincronizar`")])
    assert set(AlertaEntrada.model_fields) <= set(campos)
    assert set(AlertaAdmin.model_fields) == set(Alerta.model_fields) | {"creado_en", "creado_por", "actualizado_por"}


def test_filas_de_la_tabla_de_admin(documento):
    """Las filas de la tabla de §5.5 son las que empiezan por la celda de una ruta de admin de alertas (otras tablas,
    como los eventos de §5.10 o las ayudas de §5.11, también nombran esas rutas, pero no en su primera celda)."""
    patron = re.compile(r"^\| `((?:GET|PUT|DELETE|POST) /v1/admin/alerts[^`]*)` \|")
    filas = [linea for linea in documento.splitlines() if patron.match(linea)]
    rutas = [patron.match(fila).group(1) for fila in filas]
    assert sorted(rutas) == sorted(set(rutas))  # una fila por ruta
    assert set(rutas) == {
        "GET /v1/admin/alerts",
        "PUT /v1/admin/alerts/{id}",
        "DELETE /v1/admin/alerts/{id}",
        "POST /v1/admin/alerts/sincronizar",
    }
    [sincronizar] = [fila for fila in filas if "sincronizar" in fila]
    assert f"(≤ {CAMBIOS_MAX})" in sincronizar
    for texto in ('"op": "upsert"', '"op": "eliminar"', '"estado": "ok" \\| "error"', '"VALIDACION"', '"generado_en"'):
        assert texto in sincronizar, texto


def test_conflicto_version_en_5_6_y_en_errores(documento):
    assert "`CONFLICTO_VERSION`" in _seccion(documento, "### 5.6 ", "### 5.7 ")
    assert "CONFLICTO_VERSION" in MENSAJE_POR_CODIGO


def test_rutas_del_openapi():
    rutas = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"]
    assert set(rutas["/v1/alerts"]) == {"get"}
    assert "security" not in rutas["/v1/alerts"]["get"]
    assert [p["name"] for p in rutas["/v1/alerts"]["get"]["parameters"]] == ["desde"]
    assert set(rutas["/v1/admin/alerts"]) == {"get"}
    assert [p["name"] for p in rutas["/v1/admin/alerts"]["get"]["parameters"]] == ["q", "tipo", "prioridad", "activa"]
    assert set(rutas["/v1/admin/alerts/sincronizar"]) == {"post"}
    assert set(rutas["/v1/admin/alerts/{alerta_id}"]) == {"put", "delete"}
    put = rutas["/v1/admin/alerts/{alerta_id}"]["put"]
    assert {(p["name"], p["in"]) for p in put["parameters"]} == {("alerta_id", "path"), ("if-match", "header")}
    assert {"200", "201", "409", "422"} <= set(put["responses"])
    assert all(
        op.get("security")
        for ruta in ("/v1/admin/alerts", "/v1/admin/alerts/sincronizar", "/v1/admin/alerts/{alerta_id}")
        for op in rutas[ruta].values()
    )
