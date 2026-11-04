"""Formato de error (§5.1), códigos (§5.6) y X-Request-Id en todas las respuestas."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.errores import ErrorApi


def _es_uuid4(valor: str) -> bool:
    try:
        return uuid.UUID(valor).version == 4 and valor == valor.lower()
    except ValueError:
        return False


def test_ruta_inexistente_da_404_con_formato_de_error(cliente):
    r = cliente.get("/v1/validacion-ruta-inexistente")
    assert r.status_code == 404
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}
    assert set(cuerpo["error"]) == {"codigo", "mensaje", "detalle"}
    assert cuerpo["error"]["codigo"] == "NO_ENCONTRADO"
    assert cuerpo["error"]["mensaje"]
    assert cuerpo["error"]["detalle"] is None
    assert _es_uuid4(r.headers["X-Request-Id"])


def test_reutiliza_el_x_request_id_del_cliente(cliente):
    rid = str(uuid.uuid4())
    for ruta in ("/v1/health", "/v1/validacion-ruta-inexistente"):
        r = cliente.get(ruta, headers={"X-Request-Id": rid})
        assert r.headers["X-Request-Id"] == rid


@pytest.mark.parametrize("entrante", ["a" * 129, "con espacios", 'inyeccion"json', ""])
def test_x_request_id_no_valido_se_reemplaza(cliente, entrante):
    r = cliente.get("/v1/health", headers={"X-Request-Id": entrante})
    assert r.headers["X-Request-Id"] != entrante
    assert _es_uuid4(r.headers["X-Request-Id"])


def test_metodo_no_permitido(cliente):
    r = cliente.post("/v1/health")
    assert r.status_code == 405
    error = r.json()["error"]
    assert error["codigo"] == "SOLICITUD_INVALIDA"
    assert error["detalle"] == {"metodos_permitidos": ["GET"]}
    assert "X-Request-Id" in r.headers


class _Entrada(BaseModel):
    radio_m: int = Field(ge=5, le=100)
    mensaje: str = Field(min_length=1, max_length=200)


@pytest.fixture
def cliente_con_rutas_de_prueba(app):
    @app.post("/v1/prueba/validacion")
    async def validar(entrada: _Entrada) -> dict:
        return {"ok": True}

    @app.get("/v1/prueba/fallo")
    async def fallar() -> dict:
        raise RuntimeError("detalle interno que no debe salir: secreto=xyz")

    @app.get("/v1/prueba/error-api")
    async def error_api() -> dict:
        raise ErrorApi(409, "NOMBRE_DUPLICADO", "Ya existe un lugar con ese nombre.", {"campo": "nombre"})

    with TestClient(app) as c:
        yield c


def test_validacion_da_422_con_campos(cliente_con_rutas_de_prueba):
    r = cliente_con_rutas_de_prueba.post("/v1/prueba/validacion", json={"radio_m": 1})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["codigo"] == "VALIDACION"
    campos = {c["campo"]: c["motivo"] for c in error["detalle"]["campos"]}
    assert campos == {"radio_m": "Debe ser mayor o igual que 5.", "mensaje": "Campo obligatorio."}


def test_json_mal_formado_da_400(cliente_con_rutas_de_prueba):
    r = cliente_con_rutas_de_prueba.post(
        "/v1/prueba/validacion", content=b"{no es json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "SOLICITUD_INVALIDA"


def test_excepcion_no_controlada_da_500_sin_filtrar_detalles(cliente_con_rutas_de_prueba, logs_json):
    rid = str(uuid.uuid4())
    r = cliente_con_rutas_de_prueba.get("/v1/prueba/fallo", headers={"X-Request-Id": rid})
    assert r.status_code == 500
    assert r.headers["X-Request-Id"] == rid
    error = r.json()["error"]
    assert error["codigo"] == "ERROR_INTERNO"
    assert "secreto" not in r.text
    eventos = [linea for linea in logs_json.lineas if linea["request_id"] == rid]
    assert {e["evento"] for e in eventos} >= {"error_no_controlado", "peticion"}
    fallo = next(e for e in eventos if e["evento"] == "error_no_controlado")
    assert fallo["nivel"] == "ERROR"
    assert "RuntimeError" in fallo["excepcion"]


def test_error_api_conserva_codigo_y_detalle(cliente_con_rutas_de_prueba):
    r = cliente_con_rutas_de_prueba.get("/v1/prueba/error-api")
    assert r.status_code == 409
    assert r.json() == {
        "error": {
            "codigo": "NOMBRE_DUPLICADO",
            "mensaje": "Ya existe un lugar con ese nombre.",
            "detalle": {"campo": "nombre"},
        }
    }
