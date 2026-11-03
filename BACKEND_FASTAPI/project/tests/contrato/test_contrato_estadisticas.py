"""Contrato de BE-2.3: el ejemplo y la fila de `GET /v1/admin/stats` (ARCHITECTURE §5.5) coinciden con los esquemas y
el OpenAPI. Se omite si el documento no está (p. ej. con `project/` copiado solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.esquemas.estadisticas import ResumenPanel, UltimoVideo
from app.main import crear_app

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def test_ejemplo_de_la_seccion(documento):
    seccion = _seccion(documento, "#### `GET /v1/admin/stats` (BE-2.3)", "#### `GET /v1/admin/videos` (BE-2.1)")
    [ejemplo] = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]
    assert set(ejemplo) == set(ResumenPanel.model_fields)
    assert set(ejemplo["ultimo_video"]) == set(UltimoVideo.model_fields)
    modelo = ResumenPanel.model_validate(ejemplo)
    assert modelo.model_dump(mode="json") == ejemplo  # `creado_en` del ejemplo ya está en UTC con Z y sin fracciones


def test_fila_de_la_tabla(documento):
    [fila] = [linea for linea in documento.splitlines() if linea.startswith("| `GET /v1/admin/stats` |")]
    for campo in ResumenPanel.model_fields:
        assert f'"{campo}"' in fila
    for campo in UltimoVideo.model_fields:
        assert f'"{campo}"' in fila


def test_rutas_del_openapi():
    rutas = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"]
    assert set(rutas["/v1/admin/stats"]) == {"get"}
    assert rutas["/v1/admin/stats"]["get"].get("security")
    assert "parameters" not in rutas["/v1/admin/stats"]["get"]
    esquema = rutas["/v1/admin/stats"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema == {"$ref": "#/components/schemas/ResumenPanel"}
    assert set(rutas["/v1/admin/stats/uso"]) == {"get"}  # el reservado de BE-5.2 sigue
