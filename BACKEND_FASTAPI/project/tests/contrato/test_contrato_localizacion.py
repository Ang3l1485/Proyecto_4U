"""Contrato de BE-3.2 y BE-5.1: el ejemplo y las reglas de `POST /v1/localize` y `POST /v1/localize/frame`
(ARCHITECTURE §5.3), los códigos de §5.6 y los parámetros `LOC_*` y los eventos de §5.10 coinciden con los esquemas,
`Settings`, el algoritmo y el OpenAPI. Se omite si el documento no está (p. ej. con `project/` copiado solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.api.v1.admin_diagnostico import MARGEN_MULTIPART
from app.config import Settings
from app.dominio import geo
from app.dominio.localizacion import DECIMALES_CONFIANZA, Parametros
from app.esquemas.localizacion import (
    DECIMALES_COORDENADA,
    METADATOS_MAX_BYTES,
    PARTE_FOTO,
    PARTE_FOTOS,
    PARTE_METADATOS,
    FrameRespuesta,
    LocalizacionRespuesta,
    LugarCercano,
    MetadatosFrame,
    MetadatosLocalizacion,
    PosicionPrevia,
    PosicionRespuesta,
    ReferenciaLugar,
)
from app.esquemas.videos import APP_VERSION_MAX
from app.main import crear_app
from app.servicios.localizar import parametros_de

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"
LOCALIZE = ("#### `POST /v1/localize`", "#### `POST /v1/localize/frame`")
FRAME = ("#### `POST /v1/localize/frame`", "#### `GET /v1/places`")


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def test_ejemplos_de_localize(documento):
    seccion = _seccion(documento, *LOCALIZE)
    metadatos, respuesta = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]
    assert set(metadatos) <= set(MetadatosLocalizacion.model_fields)
    assert MetadatosLocalizacion.model_validate(metadatos).origen == "escaneo"
    assert set(respuesta) == set(LocalizacionRespuesta.model_fields)
    assert set(respuesta["posicion"]) == set(PosicionRespuesta.model_fields)
    assert set(respuesta["lugar_cercano"]) == set(LugarCercano.model_fields)
    assert set(respuesta["referencias"][0]) == set(ReferenciaLugar.model_fields)
    assert respuesta["version_vector"] == Settings().embedding_version_vector
    assert respuesta["referencias"][0]["id"] != respuesta["lugar_cercano"]["id"]  # sin repetir el cercano


def test_reglas_de_localize(documento):
    seccion = _seccion(documento, *LOCALIZE)
    assert f"`{PARTE_FOTOS}`: 1 a 5 partes" in seccion and f"`{PARTE_METADATOS}`: una parte" in seccion
    assert f"de como mucho {METADATOS_MAX_BYTES:,} bytes".replace(",", " ") in seccion
    assert f"`LOC_MAX_BYTES_FOTO` + {MARGEN_MULTIPART // 1024} KiB" in seccion
    assert f"hasta {APP_VERSION_MAX} caracteres" in seccion
    assert f"**truncada** a {DECIMALES_CONFIANZA} decimales" in seccion
    assert f"`lat`/`lng` con {DECIMALES_COORDENADA} decimales" in seccion
    for codigo in ("400 FOTOS_INVALIDAS", "400 SOLICITUD_INVALIDA", "422 VALIDACION", "503 EMBEDDING_NO_DISPONIBLE",
                   "503 BASE_NO_DISPONIBLE"):  # fmt: skip
        assert codigo in seccion, codigo


def test_ejemplos_de_frame(documento):
    seccion = _seccion(documento, *FRAME)
    metadatos, respuesta = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]
    assert set(metadatos) <= set(MetadatosFrame.model_fields)
    modelo = MetadatosFrame.model_validate(metadatos)
    assert set(metadatos["posicion_previa"]) == set(PosicionPrevia.model_fields)
    ajustes = Settings()
    assert ajustes.loc_frame_radio_min_m <= modelo.radio_m <= ajustes.loc_frame_radio_max_m
    assert list(respuesta) == list(FrameRespuesta.model_fields)  # mismo orden que la serialización
    assert set(respuesta["posicion"]) == set(PosicionRespuesta.model_fields)
    assert set(respuesta["lugar_cercano"]) == set(LugarCercano.model_fields)
    assert set(respuesta["referencias"][0]) == set(ReferenciaLugar.model_fields)
    assert respuesta["version_vector"] == ajustes.embedding_version_vector
    assert respuesta["distancia_previa_m"] <= respuesta["radio_busqueda_m"]
    previa, pos = metadatos["posicion_previa"], respuesta["posicion"]
    distancia = geo.distancia_m(previa["lat"], previa["lng"], pos["lat"], pos["lng"])
    assert round(distancia, 1) == respuesta["distancia_previa_m"]  # el ejemplo es coherente


def test_reglas_de_frame(documento):
    seccion = _seccion(documento, *FRAME)
    ajustes = Settings()
    assert f"`{PARTE_FOTO}`: **una** parte" in seccion and f"`{PARTE_METADATOS}`: una parte" in seccion
    assert f"de como mucho {METADATOS_MAX_BYTES:,} bytes".replace(",", " ") in seccion
    assert f"`LOC_MAX_BYTES_FOTO` + {MARGEN_MULTIPART // 1024} KiB" in seccion
    radios = f"= [{ajustes.loc_frame_radio_min_m:g}, {ajustes.loc_frame_radio_max_m:g}] metros"
    assert radios in seccion and f"`LOC_FRAME_RADIO_M` = {ajustes.loc_frame_radio_m:g}" in seccion
    assert f"hasta {APP_VERSION_MAX} caracteres" in seccion
    for campo in ("metadatos.rumbo", "metadatos.posicion_previa.lat", "metadatos.posicion_previa.lng",
                  "metadatos.radio_m"):  # fmt: skip
        assert f"`{campo}`" in seccion, campo
    for codigo in ("400 FOTOS_INVALIDAS", "400 SOLICITUD_INVALIDA", "422 VALIDACION", "503 EMBEDDING_NO_DISPONIBLE",
                   "503 BASE_NO_DISPONIBLE"):  # fmt: skip
        assert codigo in seccion, codigo
    assert "`origen = frame`" in seccion


def test_codigos_en_5_6(documento):
    tabla = _seccion(documento, "### 5.6 ", "### 5.7 ")
    assert "en `localize` desde BE-3.2" in tabla and "`metadatos.<campo>`" in tabla
    assert "en `localize/frame` desde BE-5.1" in tabla


def _parametros_de_5_10(documento: str) -> dict[str, float]:
    """`{NOMBRE: valor}` de las filas `| `A` / `B` … | v1 / v2 … |` de §5.10 (coma decimal, `°` fuera)."""
    seccion = _seccion(documento, "### 5.10 ", "**Formato de log en detalle.**")
    valores: dict[str, float] = {}
    for fila in seccion.splitlines():
        celdas = [c.strip() for c in fila.split("|")[1:-1]]
        if len(celdas) < 2 or not celdas[0].startswith("`LOC_"):
            continue
        nombres = re.findall(r"`(LOC_[A-Z_]+)`", celdas[0])
        partes = celdas[1].split(" / ")  # «5 / 1 572 864 (1,5 MB)», «0,55 / 0,80», «30°»
        for nombre, parte in zip(nombres, partes, strict=True):
            numero = re.match(r"[0-9][0-9 ]*(?:,[0-9]+)?", parte.strip())
            valores[nombre] = float(numero.group(0).replace(" ", "").replace(",", "."))
    return valores


def test_parametros_loc_de_5_10_son_los_de_settings_y_del_algoritmo(documento):
    """Calibrar (§4.10) cambia a la vez `config.py` y §5.10: si solo cambia uno, esta prueba falla."""
    valores = _parametros_de_5_10(documento)
    ajustes = Settings()
    for nombre, valor in valores.items():
        assert getattr(ajustes, nombre.lower()) == pytest.approx(valor), nombre
    assert {"LOC_SIM_MIN", "LOC_SIM_ALTA", "LOC_NIVEL_ALTA_MIN", "LOC_NIVEL_MEDIA_MIN", "LOC_RADIO_GRUPO_M"} <= set(
        valores
    )
    assert {"LOC_FRAME_RADIO_M", "LOC_FRAME_RADIO_MIN_M", "LOC_FRAME_RADIO_MAX_M"} <= set(valores)  # BE-5.1
    assert parametros_de(ajustes) == Parametros()  # los valores por defecto del algoritmo son los de §5.10


def test_evento_de_localize_en_5_10(documento):
    seccion = _seccion(documento, "**Eventos de log**", "### 5.11 ")
    assert "| `localizacion_calculada` | `api` |" in seccion and "`nivel_confianza`" in seccion
    assert "| `frame_calculado` | `api` |" in seccion and "`imagenes_en_radio`" in seccion  # BE-5.1


def test_openapi_declara_el_multipart_publico_y_los_errores():
    operacion = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"]["/v1/localize"]["post"]
    cuerpo = operacion["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert cuerpo["required"] == [PARTE_FOTOS, PARTE_METADATOS]
    assert cuerpo["properties"][PARTE_FOTOS]["items"]["format"] == "binary"
    assert {"200", "400", "422", "503"} <= set(operacion["responses"])
    assert "security" not in operacion  # público


def test_openapi_declara_el_frame_publico_con_una_foto():
    rutas = crear_app(Settings(app_env="test", embedding_url=None)).openapi()["paths"]
    operacion = rutas["/v1/localize/frame"]["post"]
    cuerpo = operacion["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert cuerpo["required"] == [PARTE_FOTO, PARTE_METADATOS]
    assert cuerpo["properties"][PARTE_FOTO]["format"] == "binary"
    assert {"200", "400", "422", "503"} <= set(operacion["responses"]) and "501" not in operacion["responses"]
    assert "security" not in operacion
    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert esquema.endswith("/FrameRespuesta")
