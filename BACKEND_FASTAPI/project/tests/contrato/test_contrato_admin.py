"""Contrato de BE-4.1 (C5): §5.5 (videos e imágenes), §5.6, §5.7, §5.8 y §5.10 de ARCHITECTURE contra los esquemas,
los mensajes que envía `api`, `Settings` y el OpenAPI. Se omite si el documento no está."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.dominio import mensajes
from app.esquemas.videos import (
    FallidaLote,
    ImagenAdmin,
    ImagenDetalle,
    LoteResultado,
    ReferenciaVideo,
    VectorImagen,
    VideoBorrado,
)
from app.main import crear_app

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"
V = uuid.uuid4()
I = uuid.uuid4()  # noqa: E741


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def openapi() -> dict:
    return crear_app(Settings()).openapi()


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def _ejemplos(seccion: str) -> list:
    return [json.loads(bloque) for bloque in re.findall(r"```json\n(.*?)\n```", seccion, re.S)]


def test_ejemplos_de_videos_e_imagenes(documento):
    [borrado] = _ejemplos(_seccion(documento, "#### Videos: `PATCH` y `DELETE", "#### Imágenes: `/v1/admin/images`"))
    assert set(borrado) == set(VideoBorrado.model_fields)
    assert (borrado["estado"], borrado["purga"]) == ("eliminado", "programada")
    detalle, lote = _ejemplos(_seccion(documento, "#### Imágenes: `/v1/admin/images`", "#### Lugares: "))
    assert set(detalle) == set(ImagenDetalle.model_fields) == set(ImagenAdmin.model_fields) | {"video", "vector"}
    assert set(detalle["video"]) == set(ReferenciaVideo.model_fields)
    assert set(detalle["vector"]) == set(VectorImagen.model_fields)
    assert set(lote) == set(LoteResultado.model_fields)
    assert set(lote["fallidas"][0]) == set(FallidaLote.model_fields)


def test_filas_de_la_tabla_de_5_5(documento):
    tabla = _seccion(documento, "| Método y ruta | Petición | Respuesta |", "`LugarEntrada`: `nombre`")
    for ruta in (
        "`PATCH /v1/admin/videos/{id}`",
        "`DELETE /v1/admin/videos/{id}`",
        "`GET /v1/admin/images`",
        "`GET /v1/admin/images/{id}`",
        "`PATCH /v1/admin/images/{id}`",
        "`DELETE /v1/admin/images/{id}`",
        "`POST /v1/admin/images/lote`",
        "`POST /v1/admin/images/{id}/reprocesar`",
    ):
        assert sum(1 for fila in tabla.splitlines() if fila.startswith(f"| {ruta} |")) == 1, ruta


def test_rutas_metodos_y_estados_en_el_openapi(openapi):
    rutas = openapi["paths"]
    esperado = {
        ("/v1/admin/videos/{video_id}", "patch"): "200",
        ("/v1/admin/videos/{video_id}", "delete"): "202",
        ("/v1/admin/images", "get"): "200",
        ("/v1/admin/images/lote", "post"): "200",
        ("/v1/admin/images/{imagen_id}", "get"): "200",
        ("/v1/admin/images/{imagen_id}", "patch"): "200",
        ("/v1/admin/images/{imagen_id}", "delete"): "204",
        ("/v1/admin/images/{imagen_id}/reprocesar", "post"): "202",
    }
    for (ruta, metodo), estado in esperado.items():
        operacion = rutas[ruta][metodo]
        assert estado in operacion["responses"], (ruta, metodo)
        assert operacion.get("security"), (ruta, metodo)  # requiere_admin
    assert "409" in rutas["/v1/admin/images/{imagen_id}/reprocesar"]["post"]["responses"]
    parametros = {p["name"] for p in rutas["/v1/admin/images"]["get"]["parameters"]}
    assert parametros == {"video_id", "lugar_id", "estado", "calidad", "q", "pagina", "por_pagina"}


def test_codigo_nuevo_en_5_6(documento):
    assert "`IMAGEN_NO_SUBIDA`" in _seccion(documento, "### 5.6 ", "### 5.7 ")


def test_acciones_de_auditoria_en_5_7(documento):
    seccion = _seccion(documento, "### 5.7 ", "### 5.8 ")
    tabla = _seccion(seccion, "**`auditoria`: filas de BE-4.1**", "La purga del `worker`")
    for accion in ("video.renombrar", "video.eliminar", "imagen.editar", "imagen.eliminar", "imagen.reprocesar"):
        assert f"| `{accion}` |" in tabla, accion


def test_mensajes_de_5_8_con_las_claves_que_envia_api(documento):
    seccion = _seccion(documento, "**Cola `purga`**", "### 5.9 ")
    video, imagen = _ejemplos(seccion)
    assert set(video) == set(json.loads(mensajes.cuerpo_purgar_video(V, None)))
    assert set(imagen) == set(json.loads(mensajes.cuerpo_purgar_imagen(I, V, None)))
    [reprocesar] = _ejemplos(_seccion(documento, "2. **Re-procesado**", "**Cola `purga`**"))
    assert set(reprocesar) == set(json.loads(mensajes.cuerpo_reprocesar(I, None)))


def test_parametros_de_5_10(documento):
    seccion = _seccion(documento, "### 5.10 ", "**Formato de log en detalle.**")
    ajustes = Settings()
    assert re.search(rf"\| `RECONCILIADOR_CADA_MIN` \| {ajustes.reconciliador_cada_min} \|", seccion)
    assert f"| 900 / {ajustes.presign_get_ttl_s} |" in seccion
