"""Contrato de BE-2.4: el ejemplo y las reglas de `POST /v1/admin/diagnostico/vecinos` (ARCHITECTURE §5.5), el código
`FOTOS_INVALIDAS` (§5.6) y los parámetros y eventos de §5.10 coinciden con los esquemas, `Settings` y el OpenAPI. Se
omite si el documento no está (p. ej. con `project/` copiado solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.api.v1.admin_diagnostico import MARGEN_MULTIPART, PARTE_FOTO
from app.config import Settings
from app.errores import MENSAJE_POR_CODIGO
from app.esquemas.diagnostico import K_MAX, K_MIN, K_POR_DEFECTO, VecinoDiagnostico, VecinosRespuesta
from app.main import crear_app

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def test_ejemplo_de_vecinos(documento):
    seccion = _seccion(documento, "#### `POST /v1/admin/diagnostico/vecinos`", "### 5.6 ")
    [respuesta] = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]
    assert set(respuesta) == set(VecinosRespuesta.model_fields)
    [vecino] = respuesta["vecinos"]
    assert set(vecino) == set(VecinoDiagnostico.model_fields)
    assert respuesta["version_vector"] == Settings().embedding_version_vector
    assert f"entero de {K_MIN} a {K_MAX}, por defecto {K_POR_DEFECTO}" in seccion
    assert f"una sola parte `{PARTE_FOTO}`" in seccion
    assert f"`LOC_MAX_BYTES_FOTO` + {MARGEN_MULTIPART // 1024} KiB" in seccion


def test_fotos_invalidas_en_5_6_y_en_errores(documento):
    tabla = _seccion(documento, "### 5.6 ", "### 5.7 ")
    assert "| 400 | `FOTOS_INVALIDAS` |" in tabla and "`detalle.motivo`" in tabla
    assert "FOTOS_INVALIDAS" in MENSAJE_POR_CODIGO


def test_parametros_y_eventos_de_5_10(documento):
    seccion = _seccion(documento, "### 5.10 ", "### 5.11 ")
    ajustes = Settings()
    assert f"| `LOC_MAX_FOTOS` / `LOC_MAX_BYTES_FOTO` | {ajustes.loc_max_fotos} / 1 572 864 (1,5 MB) |" in seccion
    assert ajustes.loc_max_bytes_foto == 1_572_864
    assert f"| `LOC_TOP_K` / `LOC_EF_SEARCH` | {ajustes.loc_top_k} / {ajustes.loc_ef_search} |" in seccion
    assert f"| `EMBEDDING_VERSION_VECTOR` | `{ajustes.embedding_version_vector}` |" in seccion
    for evento, proceso in (
        ("vecinos_consultados", "`api`"),
        ("embedding_no_disponible", "`api`"),
        ("version_vector_distinta", "`worker`, `api`"),
    ):
        assert f"| `{evento}` | {proceso} |" in seccion, evento


def test_openapi_declara_el_multipart_k_y_los_errores():
    operacion = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"][
        "/v1/admin/diagnostico/vecinos"
    ]["post"]
    cuerpo = operacion["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert cuerpo["required"] == [PARTE_FOTO] and cuerpo["properties"][PARTE_FOTO]["format"] == "binary"
    [k] = operacion["parameters"]
    assert (k["name"], k["in"], k["schema"]["minimum"], k["schema"]["maximum"], k["schema"]["default"]) == (
        "k",
        "query",
        K_MIN,
        K_MAX,
        K_POR_DEFECTO,
    )
    assert {"200", "400", "401", "403", "422", "503"} <= set(operacion["responses"])
    assert {"jwt": []} in operacion["security"]
