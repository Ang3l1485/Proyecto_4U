"""Comprobación de disponibilidad de embeddings."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.clientes.embedding import (
    EmbeddingNoDisponible,
    ImagenRechazada,
    RespuestaNoValida,
    esta_listo,
    vectorizar,
)
from app.config import Settings

AJUSTES = Settings(embedding_url="http://embedding.prueba:8080")


def _transporte(manejador) -> httpx.MockTransport:
    return httpx.MockTransport(manejador)


@pytest.mark.parametrize(("estado", "esperado"), [(200, True), (503, False), (404, False)])
def test_segun_el_estado_de_health_ready(estado, esperado):
    vistas: list[str] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        vistas.append(str(peticion.url))
        return httpx.Response(estado)

    assert asyncio.run(esta_listo(AJUSTES, _transporte(manejador))) is esperado
    assert vistas == ["http://embedding.prueba:8080/health/ready"]


def test_sin_conexion_es_no_disponible():
    def manejador(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin DNS", request=peticion)

    assert asyncio.run(esta_listo(AJUSTES, _transporte(manejador))) is False


def test_sin_url_configurada_es_no_disponible():
    assert asyncio.run(esta_listo(Settings(embedding_url=None))) is False


# --- vectorizar (BE-2.2) -------------------------------------------------------------------------------------------
def _vectores(n: int, dim: int = 384, version: str = "dinov2-vits14/pp-v1") -> dict:
    return {"version_vector": version, "dim": dim, "vectores": [[0.0] * dim for _ in range(n)], "tiempos_ms": {}}


def _error(estado: int, codigo: str, indice: int | None = None) -> httpx.Response:
    detalle = {"indice": indice} if indice is not None else None
    return httpx.Response(estado, json={"error": {"codigo": codigo, "mensaje": "…", "detalle": detalle}})


def _vectorizar(manejador, imagenes=(b"a", b"b"), **kwargs):
    return asyncio.run(vectorizar(AJUSTES, list(imagenes), transporte=_transporte(manejador), **kwargs))


def test_vectorizar_envia_partes_imagenes_y_prioridad():
    vistas: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        vistas.append(peticion)
        return httpx.Response(200, json=_vectores(2))

    resultado = _vectorizar(manejador, prioridad="baja")
    assert resultado.version_vector == "dinov2-vits14/pp-v1" and len(resultado.vectores) == 2
    peticion = vistas[0]
    assert str(peticion.url) == "http://embedding.prueba:8080/v1/embed"
    assert peticion.headers["X-Prioridad"] == "baja"
    cuerpo = peticion.read()
    assert cuerpo.count(b'name="imagenes"') == 2 and cuerpo.count(b"Content-Type: image/jpeg") == 2


@pytest.mark.parametrize(
    ("respuesta", "excepcion"),
    [
        (_error(503, "NO_LISTO"), EmbeddingNoDisponible),
        (_error(503, "SATURADO"), EmbeddingNoDisponible),
        (_error(500, "ERROR_INTERNO"), EmbeddingNoDisponible),
        (_error(400, "SOLICITUD_INVALIDA"), RespuestaNoValida),
        (httpx.Response(200, json=_vectores(1)), RespuestaNoValida),  # un vector para dos imágenes
        (httpx.Response(200, json={"vectores": []}), RespuestaNoValida),
    ],
)
def test_vectorizar_errores(respuesta, excepcion):
    with pytest.raises(excepcion):
        _vectorizar(lambda peticion: respuesta)


def test_imagen_rechazada_lleva_su_indice():
    with pytest.raises(ImagenRechazada) as error:
        _vectorizar(lambda peticion: _error(400, "IMAGEN_INVALIDA", indice=1))
    assert (error.value.indice, error.value.codigo) == (1, "IMAGEN_INVALIDA")


def test_conexion_rechazada_se_reintenta_una_vez():
    intentos: list[int] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        intentos.append(1)
        if len(intentos) == 1:
            raise httpx.ConnectError("rechazada", request=peticion) from ConnectionRefusedError(111, "refused")
        return httpx.Response(200, json=_vectores(2))

    assert len(_vectorizar(manejador).vectores) == 2
    assert len(intentos) == 2


def test_sin_dns_o_tiempo_agotado_no_se_reintenta():
    intentos: list[int] = []

    def sin_dns(peticion: httpx.Request) -> httpx.Response:
        intentos.append(1)
        raise httpx.ConnectError("sin DNS", request=peticion)

    with pytest.raises(EmbeddingNoDisponible, match="sin conexión"):
        _vectorizar(sin_dns)
    assert len(intentos) == 1

    def lento(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=peticion)

    with pytest.raises(EmbeddingNoDisponible, match="sin respuesta en 5 s"):
        _vectorizar(lento)


def test_sin_url_no_llama():
    with pytest.raises(EmbeddingNoDisponible):
        asyncio.run(vectorizar(Settings(embedding_url=None), [b"a"]))
