"""`GET /v1/health/ready` contra una base real (BE-1.2 C4: `"db": "ok"`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import crear_app

pytestmark = pytest.mark.base


def test_ready_con_la_base_disponible(base_vacia):
    with TestClient(crear_app(base_vacia)) as cliente:
        r = cliente.get("/v1/health/ready")
        assert r.status_code == 200
        assert r.json() == {"estado": "ok", "db": "ok", "embedding": "no_disponible"}
        # Segunda llamada con la conexión del pool.
        assert cliente.get("/v1/health/ready").status_code == 200


def test_ready_con_credenciales_rechazadas_es_503(base_vacia, logs_json):
    ajustes = base_vacia.model_copy(update={"db_password": SecretStr("incorrecta")})
    with TestClient(crear_app(ajustes)) as cliente:
        r = cliente.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "BASE_NO_DISPONIBLE"
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "base_no_disponible"]
    assert "InvalidPasswordError" in evento["motivo"]
    assert "incorrecta" not in str(logs_json.lineas)
