"""Contrato de BE-2.1: los ejemplos y parámetros de ARCHITECTURE §5.4, §5.5 y §5.10 coinciden con los esquemas y
`Settings`. Se omite si el documento no está (p. ej. con `project/` copiado solo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.dominio.recoleccion import ENCABEZADOS_PUT
from app.esquemas.videos import (
    ConteoFotos,
    ImagenAdmin,
    ImagenesRegistradas,
    ImagenRegistrada,
    ImagenRegistro,
    InicioRecorrido,
    SubidaCompletada,
    SubidaPut,
    VideoCrear,
    VideoResumen,
)

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


def _campos(modelo) -> set[str]:
    return set(modelo.model_fields)


def test_ejemplo_de_crear_video(documento):
    [peticion] = _ejemplos(_seccion(documento, "#### `POST /v1/collect/videos`", "#### `POST /v1/collect/videos/{"))
    assert set(peticion) == _campos(VideoCrear)
    assert set(peticion["inicio"]) == _campos(InicioRecorrido)
    VideoCrear.model_validate(peticion)


def test_ejemplos_de_registrar_imagenes(documento):
    seccion = _seccion(
        documento,
        "#### `POST /v1/collect/videos/{video_id}/images`",
        "#### `POST /v1/collect/videos/{video_id}/complete`",
    )
    peticion, respuesta = _ejemplos(seccion)
    [elemento] = peticion["imagenes"]
    assert set(elemento) == _campos(ImagenRegistro)
    assert set(respuesta) == _campos(ImagenesRegistradas)
    [imagen] = respuesta["imagenes"]
    assert set(imagen) == _campos(ImagenRegistrada)
    assert set(imagen["subida"]) == _campos(SubidaPut)
    assert imagen["subida"]["encabezados"] == ENCABEZADOS_PUT


def test_ejemplo_de_complete(documento):
    [respuesta] = _ejemplos(_seccion(documento, "#### `POST /v1/collect/videos/{video_id}/complete`", "### 5.5 "))
    assert set(respuesta) == _campos(SubidaCompletada)
    assert set(respuesta["conteo"]) == _campos(ConteoFotos)


def test_objetos_comunes_de_5_5(documento):
    resumen, imagen = _ejemplos(_seccion(documento, "`VideoResumen`:", "`LugarAdmin` ="))
    assert set(resumen) == _campos(VideoResumen)
    assert set(resumen["conteo"]) == _campos(ConteoFotos)
    assert set(imagen) == _campos(ImagenAdmin)


def test_parametros_de_recoleccion_en_5_10(documento):
    seccion = _seccion(documento, "### 5.10 ", "**Formato de log en detalle.**")
    valores: dict[str, int] = {}
    for fila in seccion.splitlines():
        celdas = [celda.strip() for celda in fila.strip().strip("|").split("|")]
        if len(celdas) < 2 or not celdas[0].startswith("`"):
            continue
        nombres = re.findall(r"`([A-Z_]+)`", celdas[0])
        for nombre, parte in zip(nombres, celdas[1].split(" / "), strict=False):
            numero = re.match(r"[0-9][0-9 ]*", parte)  # «4 194 304 (4 MB)» → 4194304
            if numero:
                valores[nombre] = int(numero.group(0).replace(" ", ""))
    ajustes = Settings()
    for nombre in ("REC_MAX_FOTOS_VIDEO", "REC_MAX_LOTE", "REC_MAX_BYTES_FOTO", "PRESIGN_PUT_TTL_S"):
        assert valores[nombre] == getattr(ajustes, nombre.lower()), nombre
    assert (valores["PAGINA_POR_DEFECTO"], valores["PAGINA_MAX"]) == (ajustes.pagina_por_defecto, ajustes.pagina_max)
